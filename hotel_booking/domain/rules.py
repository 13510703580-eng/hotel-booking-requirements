"""Pure business rules: dates, state machine, stock arithmetic.

Nothing in this module touches the database, which makes the rules
easy to unit test and keeps them out of the service layer.
"""

import datetime

from hotel_booking.domain import enums
from hotel_booking.domain.errors import AppError, ErrorCode

#: Allowed transitions of a booking, taken from the state diagram.
_TRANSITIONS: dict[enums.BookingStatus, frozenset[enums.BookingStatus]] = {
    enums.BookingStatus.PENDING_CONFIRM: frozenset(
        {
            enums.BookingStatus.CONFIRMED,
            enums.BookingStatus.REJECTED,
            enums.BookingStatus.CANCELLED,
            enums.BookingStatus.TIMEOUT_CANCELLED,
        }
    ),
    enums.BookingStatus.CONFIRMED: frozenset(
        {
            enums.BookingStatus.CHECKED_IN,
            enums.BookingStatus.CANCELLED,
        }
    ),
    enums.BookingStatus.CHECKED_IN: frozenset(
        {enums.BookingStatus.CHECKED_OUT}
    ),
    enums.BookingStatus.CHECKED_OUT: frozenset(),
    enums.BookingStatus.CANCELLED: frozenset(),
    enums.BookingStatus.REJECTED: frozenset(),
    enums.BookingStatus.TIMEOUT_CANCELLED: frozenset(),
}

#: Statuses that may be changed by the customer (REQ-008, REQ-009).
CUSTOMER_EDITABLE = frozenset(
    {
        enums.BookingStatus.PENDING_CONFIRM,
        enums.BookingStatus.CONFIRMED,
    }
)


def can_transit(
    current: enums.BookingStatus,
    target: enums.BookingStatus,
) -> bool:
    """Check the transition table; self transitions are not allowed."""
    if current is target:
        return False
    return target in _TRANSITIONS.get(current, frozenset())


def require_transition(
    current: enums.BookingStatus,
    target: enums.BookingStatus,
) -> None:
    """Raise an actionable error when a transition is forbidden."""
    if can_transit(current, target):
        return
    raise AppError(
        ErrorCode.STATE_NOT_ALLOWED,
        reason=(
            f"预订当前为“{status_label(current)}”，"
            f"不能变更为“{status_label(target)}”。"
        ),
        advice="确认订单是否已被取消或已入住，刷新后再操作。",
        target="订单详情",
    )


def status_label(status: enums.BookingStatus) -> str:
    """Human readable Chinese label of a booking status."""
    labels = {
        enums.BookingStatus.PENDING_CONFIRM: "待确认",
        enums.BookingStatus.CONFIRMED: "已确认",
        enums.BookingStatus.CHECKED_IN: "已入住",
        enums.BookingStatus.CHECKED_OUT: "已离店",
        enums.BookingStatus.CANCELLED: "已取消",
        enums.BookingStatus.REJECTED: "已拒绝",
        enums.BookingStatus.TIMEOUT_CANCELLED: "超时取消",
    }
    return labels[status]


def today() -> datetime.date:
    """Single place to obtain the current date, easy to patch in tests."""
    return datetime.date.today()


def validate_date_range(
    check_in: datetime.date,
    check_out: datetime.date,
    earliest: datetime.date | None = None,
) -> int:
    """Validate the stay dates and return the number of nights."""
    if check_out <= check_in:
        raise AppError(
            ErrorCode.INVALID_DATE_RANGE,
            reason="离店日期必须晚于入住日期。",
            advice="把离店日期改到入住日期之后至少一天。",
            target="日期选择",
        )
    limit = earliest if earliest is not None else today()
    if check_in < limit:
        raise AppError(
            ErrorCode.INVALID_DATE_RANGE,
            reason="入住日期不能早于今天。",
            advice="选择今天或之后的日期。",
            target="日期选择",
        )
    nights = (check_out - check_in).days
    if nights > 30:
        raise AppError(
            ErrorCode.INVALID_DATE_RANGE,
            reason="单次预订不能超过 30 晚。",
            advice="拆分为多次预订，或联系酒店协商长住。",
            target="日期选择",
        )
    return nights


def validate_rooms(rooms: int) -> int:
    """A booking must ask for between one and five rooms."""
    if rooms < 1 or rooms > 5:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            reason="预订间数必须在 1 到 5 之间。",
            advice="调整间数后重新提交。",
            target="预订面板",
        )
    return rooms


def validate_price(price_cents: int) -> int:
    """Prices are stored as non-negative integer cents."""
    if price_cents < 0:
        raise AppError(
            ErrorCode.PRICE_INVALID,
            reason="价格不能为负数。",
            advice="填写不小于 0 的价格。",
            target="房型与价格",
        )
    if price_cents > 10_000_00:
        raise AppError(
            ErrorCode.PRICE_INVALID,
            reason="单价超过 10000 元，疑似录入错误。",
            advice="核对单价后重新保存。",
            target="房型与价格",
        )
    return price_cents


def total_amount(unit_price_cents: int, nights: int, rooms: int) -> int:
    """Total price = unit price x nights x rooms (REQ-003 snapshot)."""
    return unit_price_cents * nights * rooms


def inventory_shortage(
    required: int,
    available: int,
) -> int:
    """Return the missing room count, zero when stock is sufficient."""
    return max(required - available, 0)


def describe_shortage(
    stay_date: datetime.date,
    required: int,
    available: int,
    stopped: bool,
) -> AppError:
    """Build the precise "why no room" error required by REQ-012."""
    if stopped:
        return AppError(
            ErrorCode.STOPPED_FOR_SALE,
            reason=f"{stay_date.isoformat()} 酒店停售，不接收新预订。",
            advice="换一个入住日期，或选择同城其他酒店。",
            target="查询可订房型",
        )
    if available <= 0:
        return AppError(
            ErrorCode.NO_INVENTORY,
            reason=f"{stay_date.isoformat()} 该房型已售完。",
            advice="调整入住日期，或选择其他房型。",
            target="查询可订房型",
        )
    return AppError(
        ErrorCode.NO_INVENTORY,
        reason=(
            f"{stay_date.isoformat()} 仅剩 {available} 间，"
            f"不足 {required} 间。"
        ),
        advice="减少间数，或调整日期分两笔预订。",
        target="预订面板",
    )
