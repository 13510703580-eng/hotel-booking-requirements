"""Stock maintenance and search tests (REQ-004, REQ-005)."""

import datetime

import pytest

from hotel_booking.domain.errors import AppError, ErrorCode


def test_upsert_keeps_one_row_per_room_and_date(app, staff, today):
    day = today + datetime.timedelta(days=2)
    app.inventory.set_daily_inventory(staff, "R1001", day, 5, 42800)
    app.inventory.set_daily_inventory(staff, "R1001", day, 3, 50000)
    rows = app.inventory.range_stock(
        "R1001", day, day + datetime.timedelta(days=1)
    )
    assert len(rows) == 1
    assert rows[0].available_rooms == 3


def test_price_is_stored_in_cents(app, staff, today):
    day = today + datetime.timedelta(days=3)
    app.inventory.set_daily_inventory(staff, "R1001", day, 2, 65500)
    assert app.inventory.stock_of("R1001", day).price_cents == 65500


def test_negative_stock_is_rejected(app, staff, today):
    with pytest.raises(AppError) as info:
        app.inventory.set_daily_inventory(
            staff, "R1001", today + datetime.timedelta(days=1), -1, 42800
        )
    assert info.value.code is ErrorCode.VALIDATION_FAILED


def test_search_filters_by_capacity(app, today):
    day = today + datetime.timedelta(days=1)
    hits = app.inventory.search("南京", day, day + datetime.timedelta(days=1), guests=2)
    assert all(hit.capacity >= 2 for hit in hits)
    assert {hit.room_type_id for hit in hits} == {"R1001", "R1002", "R2001"}


def test_search_filters_by_keyword(app, today):
    day = today + datetime.timedelta(days=1)
    hits = app.inventory.search(
        "南京", day, day + datetime.timedelta(days=1),
        guests=1, keyword="单人",
    )
    assert [hit.room_type_id for hit in hits] == ["R2002"]


def test_search_filters_by_price_ceiling(app, today):
    day = today + datetime.timedelta(days=1)
    hits = app.inventory.search(
        "南京", day, day + datetime.timedelta(days=1),
        max_total_cents=40000,
    )
    assert [hit.room_type_id for hit in hits] == ["R2002"]


def test_search_skips_stopped_dates(app, staff, today):
    start = today + datetime.timedelta(days=1)
    app.inventory.set_stopped(
        staff, "R1001", start, start + datetime.timedelta(days=1), True
    )
    hits = app.inventory.search("南京", start, start + datetime.timedelta(days=1))
    assert "R1001" not in {hit.room_type_id for hit in hits}


def test_search_requires_every_night(app, staff, today):
    start = today + datetime.timedelta(days=1)
    end = start + datetime.timedelta(days=3)
    app.inventory.set_stopped(staff, "R1001", start + datetime.timedelta(days=2), end, True)
    hits = app.inventory.search("南京", start, end)
    assert "R1001" not in {hit.room_type_id for hit in hits}


def test_search_rejects_empty_city(app, today):
    day = today + datetime.timedelta(days=1)
    with pytest.raises(AppError) as info:
        app.inventory.search("", day, day + datetime.timedelta(days=1))
    assert "城市" in info.value.reason


def test_bulk_set_covers_each_day(app, staff, today):
    start = today + datetime.timedelta(days=1)
    end = start + datetime.timedelta(days=4)
    count = app.inventory.bulk_set(staff, "R1001", start, end, 4, 42800)
    assert count == 4
    rows = app.inventory.range_stock("R1001", start, end)
    assert len(rows) == 4
    assert all(row.total_rooms == 4 for row in rows)


def test_customer_cannot_change_stock(app, customer, today):
    with pytest.raises(AppError) as info:
        app.inventory.set_daily_inventory(
            customer, "R1001", today + datetime.timedelta(days=1), 6, 42800
        )
    assert info.value.code is ErrorCode.FORBIDDEN
