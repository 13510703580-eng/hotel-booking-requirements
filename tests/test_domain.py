"""Unit tests of the pure rules: dates, state machine, errors."""

import datetime

import pytest

from hotel_booking.domain import enums, rules
from hotel_booking.domain.errors import AppError, ErrorCode


def test_date_range_returns_nights():
    start = datetime.date(2026, 12, 1)
    end = datetime.date(2026, 12, 4)
    assert rules.validate_date_range(start, end, start) == 3


def test_date_range_rejects_reverse_order():
    with pytest.raises(AppError) as info:
        rules.validate_date_range(
            datetime.date(2026, 12, 4), datetime.date(2026, 12, 1)
        )
    assert info.value.code is ErrorCode.INVALID_DATE_RANGE
    assert "离店日期" in info.value.reason
    assert info.value.advice


def test_date_range_rejects_past_date():
    past = datetime.date(2020, 1, 1)
    with pytest.raises(AppError):
        rules.validate_date_range(past, past + datetime.timedelta(days=1))


@pytest.mark.parametrize(
    ("source", "target", "allowed"),
    [
        (enums.BookingStatus.PENDING_CONFIRM,
         enums.BookingStatus.CONFIRMED, True),
        (enums.BookingStatus.PENDING_CONFIRM,
         enums.BookingStatus.CANCELLED, True),
        (enums.BookingStatus.CONFIRMED,
         enums.BookingStatus.CHECKED_IN, True),
        (enums.BookingStatus.CHECKED_IN,
         enums.BookingStatus.CHECKED_OUT, True),
        (enums.BookingStatus.CANCELLED,
         enums.BookingStatus.CONFIRMED, False),
        (enums.BookingStatus.CHECKED_IN,
         enums.BookingStatus.CANCELLED, False),
        (enums.BookingStatus.CHECKED_OUT,
         enums.BookingStatus.CHECKED_IN, False),
        (enums.BookingStatus.CONFIRMED,
         enums.BookingStatus.PENDING_CONFIRM, False),
    ],
)
def test_state_machine(source, target, allowed):
    assert rules.can_transit(source, target) is allowed


def test_require_transition_message_is_actionable():
    with pytest.raises(AppError) as info:
        rules.require_transition(
            enums.BookingStatus.CHECKED_IN,
            enums.BookingStatus.CANCELLED,
        )
    error = info.value
    assert error.code is ErrorCode.STATE_NOT_ALLOWED
    assert "已入住" in error.reason
    assert rules.status_label(enums.BookingStatus.CHECKED_IN) in error.reason
    assert error.target


def test_shortage_message_mentions_remaining_rooms():
    error = rules.describe_shortage(
        datetime.date(2026, 12, 1), 2, 1, False
    )
    assert error.code is ErrorCode.NO_INVENTORY
    assert "仅剩 1 间" in error.reason


def test_stopped_message_is_different_from_sold_out():
    error = rules.describe_shortage(
        datetime.date(2026, 12, 1), 1, 0, True
    )
    assert error.code is ErrorCode.STOPPED_FOR_SALE
    assert "停售" in error.reason


def test_total_amount_uses_snapshot_price():
    assert rules.total_amount(50000, 2, 3) == 300000


def test_error_rendering_has_three_parts():
    error = AppError(ErrorCode.ACCOUNT_EXISTS)
    text = error.as_message()
    assert "建议" in text and "下一步" in text
