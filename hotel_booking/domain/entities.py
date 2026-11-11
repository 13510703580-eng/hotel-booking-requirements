"""Persisted entities of the hotel booking system.

The classes here mirror the domain class diagram of experiment two.
They are plain data carriers plus a few queries that belong to the
object itself (number of nights, whether a status transition is
allowed).  Database access lives in :mod:`hotel_booking.data`.

All money values are integer cents to avoid floating point rounding.
"""

import dataclasses
import datetime
from typing import Optional

from hotel_booking.domain import enums, rules


@dataclasses.dataclass(slots=True)
class User:
    """An account of one of the three roles (REQ-001)."""

    user_id: str
    phone: str
    password_hash: str
    role: enums.Role
    display_name: str
    hotel_id: Optional[str] = None
    enabled: bool = True

    def masked_phone(self) -> str:
        """Return the phone number with the middle digits hidden."""
        if len(self.phone) < 7:
            return "***"
        return f"{self.phone[:3]}****{self.phone[-4:]}"


@dataclasses.dataclass(slots=True)
class Hotel:
    """A hotel owned by a staff account (REQ-002, REQ-016)."""

    hotel_id: str
    name: str
    city: str
    address: str
    star: int
    status: enums.HotelStatus
    staff_id: str

    def is_bookable(self) -> bool:
        """Online and warned hotels still accept bookings (REQ-002)."""
        return self.status in (
            enums.HotelStatus.ONLINE,
            enums.HotelStatus.WARNING,
        )


@dataclasses.dataclass(slots=True)
class RoomType:
    """A sellable room type of a hotel (REQ-003)."""

    room_type_id: str
    hotel_id: str
    name: str
    capacity: int
    bed_type: str
    base_price_cents: int
    sale_status: enums.SaleStatus = enums.SaleStatus.ON_SALE


@dataclasses.dataclass(slots=True)
class DailyInventory:
    """One row per (room type, date), the unit of stock (REQ-004)."""

    room_type_id: str
    stay_date: datetime.date
    total_rooms: int
    available_rooms: int
    price_cents: int
    stopped: bool = False

    def sellable_rooms(self) -> int:
        """Return how many rooms may still be sold on this date."""
        if self.stopped:
            return 0
        return max(self.available_rooms, 0)


@dataclasses.dataclass(slots=True)
class Booking:
    """A reservation with a price snapshot (REQ-006 to REQ-012)."""

    booking_id: str
    customer_id: str
    hotel_id: str
    room_type_id: str
    check_in: datetime.date
    check_out: datetime.date
    rooms: int
    unit_price_cents: int
    total_cents: int
    status: enums.BookingStatus
    idempotency_key: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    cancel_reason: str = ""
    operator_id: str = ""

    def nights(self) -> int:
        """Number of stay dates covered by this booking."""
        return (self.check_out - self.check_in).days

    def dates(self) -> list[datetime.date]:
        """Every stay date, used for per-day stock handling."""
        return [
            self.check_in + datetime.timedelta(days=offset)
            for offset in range(self.nights())
        ]

    def is_active(self) -> bool:
        """Whether the booking still holds inventory."""
        return self.status in enums.ACTIVE_STATUSES

    def can_transit_to(self, target: enums.BookingStatus) -> bool:
        """Delegate to the state machine in :mod:`rules`."""
        return rules.can_transit(self.status, target)


@dataclasses.dataclass(slots=True)
class OperationLog:
    """One audit record written in the same transaction (REQ-014/020)."""

    log_id: str
    operator_id: str
    operator_role: str
    object_type: str
    object_id: str
    action: str
    before_state: str
    after_state: str
    result: str
    created_at: datetime.datetime
    detail: str = ""

    def masked_detail(self) -> str:
        """Hide phone numbers before showing the log to an admin."""
        return _mask_phone_numbers(self.detail)


def _mask_phone_numbers(text: str) -> str:
    """Replace 11-digit mobile numbers with a masked form."""
    digits: list[str] = []
    masked: list[str] = []
    for char in text:
        if char.isdigit():
            digits.append(char)
            if len(digits) == 11:
                masked.append(f"{digits[0]}********{digits[-1]}")
                digits = []
            continue
        if digits:
            masked.append("".join(digits))
            digits = []
        masked.append(char)
    if digits:
        masked.append("".join(digits))
    return "".join(masked)
