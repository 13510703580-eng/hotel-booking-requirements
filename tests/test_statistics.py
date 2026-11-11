"""Statistics rule tests (REQ-015).

The counting rule is part of the requirement, so it is pinned here:
every stay date counts once, cancelled bookings never count, and the
occupancy rate uses the configured rooms of that single date.
"""

import datetime

import pytest

from hotel_booking.domain import enums
from hotel_booking.domain.errors import AppError, ErrorCode


def _day(today, offset: int) -> datetime.date:
    return today + datetime.timedelta(days=offset + 1)


def test_multi_night_booking_counts_on_every_stay_date(
    app, staff, customer, today,
):
    start = _day(today, 0)
    end = _day(today, 2)
    app.booking.create(customer, "R1001", start, end, 2, "stat-1")
    rows = app.statistics.daily(staff, "H1001", start, end)
    assert len(rows) == 2
    assert [row.bookings for row in rows] == [1, 1]
    assert all(row.rooms_sold == 0 for row in rows)


def test_cancelled_booking_is_excluded(app, staff, customer, today):
    start = _day(today, 0)
    end = _day(today, 1)
    booking = app.booking.create(
        customer, "R1001", start, end, 1, "stat-2"
    ).booking
    app.booking.cancel(customer, booking.booking_id, "取消")
    rows = app.statistics.daily(staff, "H1001", start, end)
    assert rows[0].bookings == 0


def test_checked_out_booking_counts_as_check_in(
    app, staff, customer, today,
):
    start = _day(today, 0)
    end = _day(today, 1)
    booking = app.booking.create(
        customer, "R1001", start, end, 3, "stat-3"
    ).booking
    app.booking.confirm(staff, booking.booking_id)
    app.booking.check_in(staff, booking.booking_id)
    app.booking.check_out(staff, booking.booking_id)
    row = app.statistics.daily(staff, "H1001", start, end)[0]
    assert row.bookings == 1
    assert row.confirmed == 1
    assert row.checked_in == 1
    assert row.rooms_sold == 3


def test_occupancy_uses_configured_rooms(app, staff, customer, today):
    start = _day(today, 0)
    day_end = _day(today, 1)
    app.inventory.set_daily_inventory(staff, "R1001", start, 2, 42800)
    booking = app.booking.create(
        customer, "R1001", start, day_end, 1, "stat-4"
    ).booking
    app.booking.confirm(staff, booking.booking_id)
    app.booking.check_in(staff, booking.booking_id)
    row = app.statistics.daily(staff, "H1001", start, day_end)[0]
    expected = round(1 * 100.0 / row.rooms_total, 1)
    assert row.occupancy == expected
    assert 0.0 <= row.occupancy <= 100.0


def test_summary_rates_are_percentages(app, staff, customer, today):
    start = _day(today, 0)
    end = _day(today, 1)
    app.booking.create(customer, "R1001", start, end, 1, "stat-5")
    summary = app.statistics.summary(staff, "H1001", start, end)
    assert summary["bookings"] == 1.0
    assert summary["confirm_rate"] == 0.0
    assert summary["occupancy"] >= 0.0


def test_customer_cannot_read_statistics(app, customer):
    start = datetime.date.today() + datetime.timedelta(days=1)
    with pytest.raises(AppError) as info:
        app.statistics.daily(customer, "H1001", start, start + datetime.timedelta(days=3))
    assert info.value.code is ErrorCode.FORBIDDEN


def test_staff_of_other_hotel_is_rejected(app, staff):
    start = datetime.date.today() + datetime.timedelta(days=1)
    with pytest.raises(AppError) as info:
        app.statistics.daily(staff, "H1002", start, start + datetime.timedelta(days=3))
    assert info.value.code is ErrorCode.FORBIDDEN
    assert enums.Role.STAFF is staff.role
