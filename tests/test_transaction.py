"""Transaction, audit log and moderation tests (REQ-014/16/19/20)."""

import datetime

import pytest

from hotel_booking.domain import enums
from hotel_booking.domain.entities import OperationLog
from hotel_booking.domain.errors import AppError, ErrorCode


def test_log_failure_rolls_back_booking_and_stock(app, customer, today):
    day = today + datetime.timedelta(days=1)
    before = app.inventory.stock_of("R1001", day).available_rooms
    app.logs.fail_next_write = True
    with pytest.raises(AppError) as info:
        app.booking.create(customer, "R1001", day, day + datetime.timedelta(days=1), 1, "rollback")
    assert info.value.code is ErrorCode.LOG_WRITE_FAILED
    after = app.inventory.stock_of("R1001", day).available_rooms
    assert after == before
    assert app.booking.list_mine(customer) == []


def test_every_successful_booking_writes_one_log(app, staff, customer, today):
    day = today + datetime.timedelta(days=1)
    booking = app.booking.create(
        customer, "R1001", day, day + datetime.timedelta(days=1), 1, "log"
    ).booking
    app.booking.confirm(staff, booking.booking_id)
    admin = app.login("13700000001", "Demo1234")
    logs = app.logs.query(admin, object_type="BOOKING", limit=50)
    actions = {item.action for item in logs}
    assert "CREATE_BOOKING" in actions
    assert "CONFIRM_BOOKING" in actions
    assert all(item.operator_role in {"CUSTOMER", "STAFF"} for item in logs)


def test_customer_cannot_read_operation_logs(app, customer):
    with pytest.raises(AppError) as info:
        app.logs.query(customer)
    assert info.value.code is ErrorCode.FORBIDDEN


def test_log_detail_masks_phone_numbers():
    log = OperationLog(
        log_id="L1",
        operator_id="U1",
        operator_role="STAFF",
        object_type="BOOKING",
        object_id="B1",
        action="CONFIRM_BOOKING",
        before_state="PENDING_CONFIRM",
        after_state="CONFIRMED",
        result="SUCCESS",
        created_at=datetime.datetime.now(),
        detail="联系手机 13800000001 确认",
    )
    assert "13800000001" not in log.masked_detail()
    assert "1********1" in log.masked_detail()


def test_retention_keeps_rows_inside_180_days(
    app, admin, customer, today,
):
    day = today + datetime.timedelta(days=1)
    app.booking.create(
        customer, "R1001", day, day + datetime.timedelta(days=1), 1, "retain"
    )
    assert app.logs.count() >= 1
    removed = app.logs.purge_expired(keep_days=180)
    assert removed == 0
    assert app.logs.count() >= 1


def test_take_offline_cancels_live_bookings(app, admin, staff, customer, today):
    day = today + datetime.timedelta(days=1)
    pending = app.booking.create(
        customer, "R1001", day, day + datetime.timedelta(days=1), 1, "offline-1"
    ).booking
    confirmed = app.booking.create(
        customer, "R1002", day, day + datetime.timedelta(days=1), 1, "offline-2"
    ).booking
    app.booking.confirm(staff, confirmed.booking_id)
    result = app.hotel.take_offline(admin, "H1001", "资质过期")
    assert result["cancelled"] == 2
    assert app.hotel.get("H1001").status is enums.HotelStatus.OFFLINE
    assert app.booking.get(customer, pending.booking_id).status is (
        enums.BookingStatus.CANCELLED
    )
    assert app.inventory.stock_of("R1001", day).available_rooms == 6
    assert app.inventory.stock_of("R1002", day).available_rooms == 6


def test_offline_hotel_disappears_from_search(app, admin, today):
    day = today + datetime.timedelta(days=1)
    app.hotel.take_offline(admin, "H1001", "违规")
    hits = app.inventory.search("南京", day, day + datetime.timedelta(days=1))
    assert all(hit.hotel_id != "H1001" for hit in hits)


def test_staff_cannot_take_offline_hotel(app, staff):
    with pytest.raises(AppError) as info:
        app.hotel.take_offline(staff, "H1001", "自己下架")
    assert info.value.code is ErrorCode.FORBIDDEN


def test_warning_keeps_hotel_online(app, admin):
    hotel = app.hotel.warn(admin, "H1001", "图片与实景不符")
    assert hotel.status is enums.HotelStatus.WARNING
    assert hotel.is_bookable() is True


def test_closure_cancels_confirmed_booking(app, staff, customer, today):
    day = today + datetime.timedelta(days=2)
    booking = app.booking.create(
        customer, "R1001", day, day + datetime.timedelta(days=1), 1, "closure"
    ).booking
    app.booking.confirm(staff, booking.booking_id)
    result = app.hotel.handle_closure(
        staff, "R1001", day, day + datetime.timedelta(days=1), "临时停业"
    )
    assert result["cancelled"] == 1
    assert app.booking.get(customer, booking.booking_id).status is (
        enums.BookingStatus.CANCELLED
    )
    assert app.inventory.stock_of("R1001", day).stopped is True
