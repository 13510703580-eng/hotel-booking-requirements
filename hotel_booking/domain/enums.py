"""Domain enumerations of the hotel booking system.

Every state that is persisted in the database is declared here as an
enumeration member so that the rest of the code never compares string
literals.  The value stored in SQLite is the enum ``value`` attribute.
"""

import enum


class Role(enum.Enum):
    """Roles that a logged-in account may hold (REQ-001)."""

    CUSTOMER = "CUSTOMER"
    STAFF = "STAFF"
    ADMIN = "ADMIN"


class HotelStatus(enum.Enum):
    """Life cycle of a hotel as maintained by the platform (REQ-002/016)."""

    ONLINE = "ONLINE"
    WARNING = "WARNING"
    OFFLINE = "OFFLINE"


class SaleStatus(enum.Enum):
    """Whether a room type can be sold at all (REQ-003)."""

    ON_SALE = "ON_SALE"
    OFF = "OFF"


class BookingStatus(enum.Enum):
    """Life cycle of a booking record (REQ-006 to REQ-012)."""

    PENDING_CONFIRM = "PENDING_CONFIRM"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    TIMEOUT_CANCELLED = "TIMEOUT_CANCELLED"


class ActionType(enum.Enum):
    """Operations that must be written to the audit log (REQ-014)."""

    REGISTER = "REGISTER"
    LOGIN = "LOGIN"
    CREATE_BOOKING = "CREATE_BOOKING"
    MODIFY_BOOKING = "MODIFY_BOOKING"
    CONFIRM_BOOKING = "CONFIRM_BOOKING"
    CANCEL_BOOKING = "CANCEL_BOOKING"
    REJECT_BOOKING = "REJECT_BOOKING"
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    SET_INVENTORY = "SET_INVENTORY"
    UPDATE_HOTEL = "UPDATE_HOTEL"
    OFFLINE_HOTEL = "OFFLINE_HOTEL"
    WARN_HOTEL = "WARN_HOTEL"


#: Statuses in which a booking still occupies inventory.
ACTIVE_STATUSES = frozenset(
    {
        BookingStatus.PENDING_CONFIRM,
        BookingStatus.CONFIRMED,
        BookingStatus.CHECKED_IN,
    }
)

#: Statuses that are excluded from the statistics counters (REQ-015).
INACTIVE_STATUSES = frozenset(
    {
        BookingStatus.CANCELLED,
        BookingStatus.REJECTED,
        BookingStatus.TIMEOUT_CANCELLED,
    }
)
