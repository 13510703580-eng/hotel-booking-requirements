"""Booking life-cycle tests (REQ-006 to REQ-013)."""

import datetime

import pytest

from hotel_booking.domain import enums
from hotel_booking.domain.errors import AppError, ErrorCode


def _day(today, offset: int) -> datetime.date:
    return today + datetime.timedelta(days=offset + 1)


def _stock(app, room_type_id, day):
    return app.inventory.stock_of(room_type_id, day).available_rooms


def test_create_reduces_stock_for_every_night(app, customer, today):
    start = _day(today, 0)
    end = _day(today, 2)
    result = app.booking.create(customer, "R1001", start, end, 2, "k-1")
    assert result.replayed is False
    assert result.booking.status is enums.BookingStatus.PENDING_CONFIRM
    assert result.booking.total_cents > 0
    assert _stock(app, "R1001", start) == 4
    assert _stock(app, "R1001", end - datetime.timedelta(days=1)) == 4


def test_create_returns_same_booking_for_same_key(app, customer, today):
    start, end = _day(today, 0), _day(today, 1)
    first = app.booking.create(customer, "R1001", start, end, 1, "same-key")
    second = app.booking.create(customer, "R1001", start, end, 1, "same-key")
    assert second.replayed is True
    assert second.booking.booking_id == first.booking.booking_id
    assert _stock(app, "R1001", start) == 5
    assert len(app.booking.list_mine(customer)) == 1


def test_create_fails_when_stock_is_exhausted(app, staff, customer, today):
    start, end = _day(today, 0), _day(today, 1)
    app.inventory.set_daily_inventory(staff, "R1001", start, 1, 42800)
    app.booking.create(customer, "R1001", start, end, 1, "a")
    with pytest.raises(AppError) as info:
        app.booking.create(customer, "R1001", start, end, 1, "b")
    assert info.value.code is ErrorCode.NO_INVENTORY
    assert "售完" in info.value.reason


def test_create_rejects_stopped_date(app, staff, customer, today):
    start, end = _day(today, 0), _day(today, 1)
    app.inventory.set_stopped(staff, "R1001", start, end, True)
    with pytest.raises(AppError) as info:
        app.booking.create(customer, "R1001", start, end, 1, "stop")
    assert info.value.code is ErrorCode.STOPPED_FOR_SALE
    assert "停售" in info.value.reason


def test_modify_changes_dates_and_keeps_consistency(
    app, customer, today,
):
    start, end = _day(today, 0), _day(today, 1)
    booking = app.booking.create(
        customer, "R1001", start, end, 1, "modify"
    ).booking
    new_end = end + datetime.timedelta(days=1)
    changed = app.booking.modify(
        customer, booking.booking_id, start, new_end
    )
    assert changed.check_out == new_end
    assert _stock(app, "R1001", end) == 5


def test_modify_is_rejected_and_original_stays_when_new_stock_is_short(
    app, staff, customer, today,
):
    start, end = _day(today, 0), _day(today, 1)
    booking = app.booking.create(
        customer, "R1001", start, end, 1, "keep"
    ).booking
    blocked = _day(today, 3)
    app.inventory.set_daily_inventory(staff, "R1001", blocked, 0, 42800)
    with pytest.raises(AppError) as info:
        app.booking.modify(
            customer, booking.booking_id, blocked,
            blocked + datetime.timedelta(days=1),
        )
    assert "原预订保持不变" in info.value.advice
    reloaded = app.booking.get(customer, booking.booking_id)
    assert reloaded.check_in == start
    assert _stock(app, "R1001", start) == 5


def test_cancel_returns_stock_once(app, customer, today):
    start, end = _day(today, 0), _day(today, 1)
    booking = app.booking.create(
        customer, "R1002", start, end, 1, "cancel"
    ).booking
    cancelled = app.booking.cancel(
        customer, booking.booking_id, "行程变化"
    )
    assert cancelled.status is enums.BookingStatus.CANCELLED
    assert _stock(app, "R1002", start) == 6
    again = app.booking.cancel(customer, booking.booking_id, "重复点击")
    assert again.status is enums.BookingStatus.CANCELLED
    assert _stock(app, "R1002", start) == 6


def test_confirm_twice_returns_original_result(app, staff, customer, today):
    booking = app.booking.create(
        customer, "R1001", _day(today, 0), _day(today, 1), 1, "confirm"
    ).booking
    first = app.booking.confirm(staff, booking.booking_id)
    second = app.booking.confirm(staff, booking.booking_id)
    assert first.status is enums.BookingStatus.CONFIRMED
    assert second.status is enums.BookingStatus.CONFIRMED
    assert second.booking_id == first.booking_id
    assert second.total_cents == first.total_cents


def test_cancelled_booking_cannot_be_confirmed(app, staff, customer, today):
    booking = app.booking.create(
        customer, "R1001", _day(today, 0), _day(today, 1), 1, "late"
    ).booking
    app.booking.cancel(customer, booking.booking_id, "不要了")
    with pytest.raises(AppError) as info:
        app.booking.confirm(staff, booking.booking_id)
    assert info.value.code is ErrorCode.STATE_NOT_ALLOWED


def test_check_out_requires_check_in(app, staff, customer, today):
    booking = app.booking.create(
        customer, "R1001", _day(today, 0), _day(today, 1), 1, "skip"
    ).booking
    app.booking.confirm(staff, booking.booking_id)
    with pytest.raises(AppError) as info:
        app.booking.check_out(staff, booking.booking_id)
    assert info.value.code is ErrorCode.STATE_NOT_ALLOWED
    assert "不能变更为" in info.value.reason


def test_checked_in_booking_cannot_be_cancelled(
    app, staff, customer, today,
):
    booking = app.booking.create(
        customer, "R1001", _day(today, 0), _day(today, 1), 1, "stay"
    ).booking
    app.booking.confirm(staff, booking.booking_id)
    app.booking.check_in(staff, booking.booking_id)
    with pytest.raises(AppError) as info:
        app.booking.cancel(customer, booking.booking_id, "退订")
    assert info.value.code is ErrorCode.STATE_NOT_ALLOWED


def test_customer_cannot_read_other_customers_booking(
    app, customer, today,
):
    other = app.register_customer("13600000003", "Demo1234", "王五")
    other_session = app.login("13600000003", "Demo1234")
    booking = app.booking.create(
        other_session, "R1001", _day(today, 0), _day(today, 1), 1, "other"
    ).booking
    with pytest.raises(AppError) as info:
        app.booking.get(customer, booking.booking_id)
    assert info.value.code is ErrorCode.FORBIDDEN


def test_staff_cannot_confirm_other_hotel_booking(
    app, staff, customer, today,
):
    other_staff = app.login("13900000002", "Demo1234")
    booking = app.booking.create(
        customer, "R2001", _day(today, 0), _day(today, 1), 1, "cross"
    ).booking
    with pytest.raises(AppError) as info:
        app.booking.confirm(staff, booking.booking_id)
    assert info.value.code is ErrorCode.FORBIDDEN
    assert app.booking.confirm(other_staff, booking.booking_id).status is (
        enums.BookingStatus.CONFIRMED
    )


def test_timeout_sweep_cancels_stale_pending_booking(
    app, customer, today,
):
    booking = app.booking.create(
        customer, "R1001", _day(today, 0), _day(today, 1), 1, "sweep"
    ).booking
    later = booking.created_at + datetime.timedelta(hours=30)
    expired = app.booking.sweep_timeout(later)
    assert expired == 1
    reloaded = app.booking.get(customer, booking.booking_id)
    assert reloaded.status is enums.BookingStatus.TIMEOUT_CANCELLED
    assert _stock(app, "R1001", _day(today, 0)) == 6
