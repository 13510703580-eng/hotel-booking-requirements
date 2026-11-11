"""Repository layer: the only place that speaks SQL.

Each method takes an open connection so that a service can group
several calls into one transaction.  Rows are converted to the
dataclasses of :mod:`hotel_booking.domain.entities` before returning.
"""

import datetime
import sqlite3
from typing import Optional

from hotel_booking.domain import entities, enums
from hotel_booking.domain.errors import AppError, ErrorCode


def _as_date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(value)


def _as_datetime(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


def _as_bool(value: int) -> bool:
    return bool(value)


class UserRepository:
    """CRUD for accounts (REQ-001, REQ-019)."""

    @staticmethod
    def insert(conn: sqlite3.Connection, user: entities.User,
               created_at: datetime.datetime) -> None:
        """Insert a new account; duplicate phones raise an error."""
        try:
            conn.execute(
                "INSERT INTO users (user_id, phone, password_hash, role, "
                "display_name, hotel_id, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user.user_id,
                    user.phone,
                    user.password_hash,
                    user.role.value,
                    user.display_name,
                    user.hotel_id,
                    int(user.enabled),
                    created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise AppError(
                ErrorCode.ACCOUNT_EXISTS,
                reason=f"手机号 {user.masked_phone()} 已注册。",
                advice="直接登录，或换一个手机号注册。",
                target="登录页",
            ) from exc

    @staticmethod
    def get_by_phone(
        conn: sqlite3.Connection, phone: str
    ) -> Optional[entities.User]:
        """Find an account by phone number."""
        row = conn.execute(
            "SELECT * FROM users WHERE phone = ?", (phone,)
        ).fetchone()
        if row is None:
            return None
        return _user_from_row(row)

    @staticmethod
    def get_by_id(
        conn: sqlite3.Connection, user_id: str
    ) -> Optional[entities.User]:
        """Find an account by identifier."""
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return None if row is None else _user_from_row(row)

    @staticmethod
    def set_enabled(
        conn: sqlite3.Connection, user_id: str, enabled: bool
    ) -> None:
        """Enable or disable an account."""
        conn.execute(
            "UPDATE users SET enabled = ? WHERE user_id = ?",
            (int(enabled), user_id),
        )


def _user_from_row(row: sqlite3.Row) -> entities.User:
    return entities.User(
        user_id=row["user_id"],
        phone=row["phone"],
        password_hash=row["password_hash"],
        role=enums.Role(row["role"]),
        display_name=row["display_name"],
        hotel_id=row["hotel_id"],
        enabled=_as_bool(row["enabled"]),
    )


class HotelRepository:
    """Hotel master data and platform moderation (REQ-002/016)."""

    @staticmethod
    def insert(conn: sqlite3.Connection, hotel: entities.Hotel) -> None:
        """Insert a hotel record."""
        conn.execute(
            "INSERT INTO hotels (hotel_id, name, city, address, star, "
            "status, staff_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                hotel.hotel_id,
                hotel.name,
                hotel.city,
                hotel.address,
                hotel.star,
                hotel.status.value,
                hotel.staff_id,
            ),
        )

    @staticmethod
    def get(
        conn: sqlite3.Connection, hotel_id: str
    ) -> Optional[entities.Hotel]:
        """Load one hotel by identifier."""
        row = conn.execute(
            "SELECT * FROM hotels WHERE hotel_id = ?", (hotel_id,)
        ).fetchone()
        return None if row is None else _hotel_from_row(row)

    @staticmethod
    def list_by_city(
        conn: sqlite3.Connection,
        city: str,
        only_online: bool = True,
    ) -> list[entities.Hotel]:
        """List hotels of a city, optionally hiding offline ones."""
        sql = "SELECT * FROM hotels WHERE city = ?"
        params: list[object] = [city]
        if only_online:
            sql += " AND status = ?"
            params.append(enums.HotelStatus.ONLINE.value)
        rows = conn.execute(sql, params).fetchall()
        return [_hotel_from_row(row) for row in rows]

    @staticmethod
    def update_info(
        conn: sqlite3.Connection,
        hotel_id: str,
        name: str,
        address: str,
        star: int,
    ) -> None:
        """Update editable fields of a hotel."""
        conn.execute(
            "UPDATE hotels SET name = ?, address = ?, star = ? "
            "WHERE hotel_id = ?",
            (name, address, star, hotel_id),
        )

    @staticmethod
    def update_status(
        conn: sqlite3.Connection,
        hotel_id: str,
        status: enums.HotelStatus,
    ) -> None:
        """Change the moderation status of a hotel."""
        conn.execute(
            "UPDATE hotels SET status = ? WHERE hotel_id = ?",
            (status.value, hotel_id),
        )


def _hotel_from_row(row: sqlite3.Row) -> entities.Hotel:
    return entities.Hotel(
        hotel_id=row["hotel_id"],
        name=row["name"],
        city=row["city"],
        address=row["address"],
        star=row["star"],
        status=enums.HotelStatus(row["status"]),
        staff_id=row["staff_id"],
    )


class RoomTypeRepository:
    """Room types and their base price (REQ-003)."""

    @staticmethod
    def insert(
        conn: sqlite3.Connection, room: entities.RoomType
    ) -> None:
        """Insert a room type."""
        conn.execute(
            "INSERT INTO room_types (room_type_id, hotel_id, name, "
            "capacity, bed_type, base_price_cents, sale_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                room.room_type_id,
                room.hotel_id,
                room.name,
                room.capacity,
                room.bed_type,
                room.base_price_cents,
                room.sale_status.value,
            ),
        )

    @staticmethod
    def get(
        conn: sqlite3.Connection, room_type_id: str
    ) -> Optional[entities.RoomType]:
        """Load one room type."""
        row = conn.execute(
            "SELECT * FROM room_types WHERE room_type_id = ?",
            (room_type_id,),
        ).fetchone()
        return None if row is None else _room_from_row(row)

    @staticmethod
    def list_by_hotel(
        conn: sqlite3.Connection, hotel_id: str
    ) -> list[entities.RoomType]:
        """List all room types of a hotel."""
        rows = conn.execute(
            "SELECT * FROM room_types WHERE hotel_id = ? ORDER BY name",
            (hotel_id,),
        ).fetchall()
        return [_room_from_row(row) for row in rows]

    @staticmethod
    def update(
        conn: sqlite3.Connection,
        room_type_id: str,
        name: str,
        capacity: int,
        bed_type: str,
        base_price_cents: int,
        sale_status: enums.SaleStatus,
    ) -> None:
        """Update the editable attributes of a room type."""
        conn.execute(
            "UPDATE room_types SET name = ?, capacity = ?, bed_type = ?, "
            "base_price_cents = ?, sale_status = ? WHERE room_type_id = ?",
            (
                name,
                capacity,
                bed_type,
                base_price_cents,
                sale_status.value,
                room_type_id,
            ),
        )


def _room_from_row(row: sqlite3.Row) -> entities.RoomType:
    return entities.RoomType(
        room_type_id=row["room_type_id"],
        hotel_id=row["hotel_id"],
        name=row["name"],
        capacity=row["capacity"],
        bed_type=row["bed_type"],
        base_price_cents=row["base_price_cents"],
        sale_status=enums.SaleStatus(row["sale_status"]),
    )


class InventoryRepository:
    """Per-day stock with conditional updates (REQ-004, REQ-018)."""

    @staticmethod
    def upsert(conn: sqlite3.Connection,
               item: entities.DailyInventory) -> None:
        """Insert or update one (room type, date) row."""
        conn.execute(
            "INSERT INTO inventory (room_type_id, stay_date, total_rooms, "
            "available_rooms, price_cents, stopped) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (room_type_id, stay_date) DO UPDATE SET "
            "total_rooms = excluded.total_rooms, "
            "available_rooms = excluded.available_rooms, "
            "price_cents = excluded.price_cents, "
            "stopped = excluded.stopped",
            (
                item.room_type_id,
                item.stay_date.isoformat(),
                item.total_rooms,
                item.available_rooms,
                item.price_cents,
                int(item.stopped),
            ),
        )

    @staticmethod
    def get(
        conn: sqlite3.Connection,
        room_type_id: str,
        stay_date: datetime.date,
    ) -> Optional[entities.DailyInventory]:
        """Load stock of one room type on one date."""
        row = conn.execute(
            "SELECT * FROM inventory WHERE room_type_id = ? "
            "AND stay_date = ?",
            (room_type_id, stay_date.isoformat()),
        ).fetchone()
        return None if row is None else _inventory_from_row(row)

    @staticmethod
    def list_range(
        conn: sqlite3.Connection,
        room_type_id: str,
        start: datetime.date,
        end: datetime.date,
    ) -> list[entities.DailyInventory]:
        """List stock rows of the half-open range [start, end)."""
        rows = conn.execute(
            "SELECT * FROM inventory WHERE room_type_id = ? "
            "AND stay_date >= ? AND stay_date < ? ORDER BY stay_date",
            (room_type_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [_inventory_from_row(row) for row in rows]

    @staticmethod
    def try_reserve(
        conn: sqlite3.Connection,
        room_type_id: str,
        stay_date: datetime.date,
        rooms: int,
    ) -> bool:
        """Atomically take ``rooms`` from one date.

        The ``available_rooms >= ?`` predicate is the whole oversell
        protection: two transactions can read the same value, but only
        the one whose UPDATE still satisfies the predicate wins.
        """
        cursor = conn.execute(
            "UPDATE inventory SET available_rooms = available_rooms - ? "
            "WHERE room_type_id = ? AND stay_date = ? AND stopped = 0 "
            "AND available_rooms >= ?",
            (rooms, room_type_id, stay_date.isoformat(), rooms),
        )
        return cursor.rowcount == 1

    @staticmethod
    def release(
        conn: sqlite3.Connection,
        room_type_id: str,
        stay_date: datetime.date,
        rooms: int,
    ) -> None:
        """Give rooms back, never exceeding the configured total."""
        conn.execute(
            "UPDATE inventory SET available_rooms = MIN("
            "available_rooms + ?, total_rooms) "
            "WHERE room_type_id = ? AND stay_date = ?",
            (rooms, room_type_id, stay_date.isoformat()),
        )

    @staticmethod
    def set_stopped(
        conn: sqlite3.Connection,
        room_type_id: str,
        start: datetime.date,
        end: datetime.date,
        stopped: bool,
    ) -> int:
        """Mark a date range as stopped / resumed (REQ-012)."""
        cursor = conn.execute(
            "UPDATE inventory SET stopped = ? WHERE room_type_id = ? "
            "AND stay_date >= ? AND stay_date < ?",
            (int(stopped), room_type_id, start.isoformat(), end.isoformat()),
        )
        return cursor.rowcount


def _inventory_from_row(row: sqlite3.Row) -> entities.DailyInventory:
    return entities.DailyInventory(
        room_type_id=row["room_type_id"],
        stay_date=_as_date(row["stay_date"]),
        total_rooms=row["total_rooms"],
        available_rooms=row["available_rooms"],
        price_cents=row["price_cents"],
        stopped=_as_bool(row["stopped"]),
    )


class BookingRepository:
    """Booking records with an idempotency key (REQ-006/013)."""

    @staticmethod
    def insert(conn: sqlite3.Connection, booking: entities.Booking) -> None:
        """Insert a booking; the unique key makes replays fail."""
        try:
            conn.execute(
                "INSERT INTO bookings (booking_id, customer_id, hotel_id, "
                "room_type_id, check_in, check_out, rooms, unit_price_cents, "
                "total_cents, status, idempotency_key, created_at, "
                "updated_at, cancel_reason, operator_id) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    booking.booking_id,
                    booking.customer_id,
                    booking.hotel_id,
                    booking.room_type_id,
                    booking.check_in.isoformat(),
                    booking.check_out.isoformat(),
                    booking.rooms,
                    booking.unit_price_cents,
                    booking.total_cents,
                    booking.status.value,
                    booking.idempotency_key,
                    booking.created_at.isoformat(),
                    booking.updated_at.isoformat(),
                    booking.cancel_reason,
                    booking.operator_id,
                ),
            )
        except sqlite3.IntegrityError:
            # A concurrent request inserted the same idempotency key.
            raise AppError(
                ErrorCode.IDEMPOTENT_REPLAY,
                reason="同一份提交已经创建过预订。",
                advice="在“我的预订”中查看已有订单，不要重复提交。",
                target="我的预订",
            ) from None

    @staticmethod
    def get(
        conn: sqlite3.Connection, booking_id: str
    ) -> Optional[entities.Booking]:
        """Load one booking."""
        row = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        return None if row is None else _booking_from_row(row)

    @staticmethod
    def get_by_key(
        conn: sqlite3.Connection, idempotency_key: str
    ) -> Optional[entities.Booking]:
        """Look up a booking by its client generated idempotency key."""
        row = conn.execute(
            "SELECT * FROM bookings WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return None if row is None else _booking_from_row(row)

    @staticmethod
    def list_by_customer(
        conn: sqlite3.Connection, customer_id: str
    ) -> list[entities.Booking]:
        """List bookings of one customer, newest first."""
        rows = conn.execute(
            "SELECT * FROM bookings WHERE customer_id = ? "
            "ORDER BY created_at DESC",
            (customer_id,),
        ).fetchall()
        return [_booking_from_row(row) for row in rows]

    @staticmethod
    def list_by_hotel(
        conn: sqlite3.Connection,
        hotel_id: str,
        statuses: tuple[enums.BookingStatus, ...] | None = None,
    ) -> list[entities.Booking]:
        """List bookings of a hotel, optionally filtered by status."""
        sql = "SELECT * FROM bookings WHERE hotel_id = ?"
        params: list[object] = [hotel_id]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            sql += f" AND status IN ({placeholders})"
            params.extend(status.value for status in statuses)
        sql += " ORDER BY check_in, created_at"
        rows = conn.execute(sql, params).fetchall()
        return [_booking_from_row(row) for row in rows]

    @staticmethod
    def update_status(
        conn: sqlite3.Connection,
        booking_id: str,
        expected: enums.BookingStatus,
        target: enums.BookingStatus,
        operator_id: str,
        cancel_reason: str = "",
        updated_at: datetime.datetime | None = None,
    ) -> bool:
        """Compare-and-set the status; False means someone got there first."""
        stamp = (updated_at or datetime.datetime.now()).isoformat()
        cursor = conn.execute(
            "UPDATE bookings SET status = ?, updated_at = ?, "
            "operator_id = ?, cancel_reason = ? "
            "WHERE booking_id = ? AND status = ?",
            (
                target.value,
                stamp,
                operator_id,
                cancel_reason,
                booking_id,
                expected.value,
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def update_stay(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        conn: sqlite3.Connection,
        booking_id: str,
        expected: enums.BookingStatus,
        room_type_id: str,
        check_in: datetime.date,
        check_out: datetime.date,
        rooms: int,
        unit_price_cents: int,
        total_cents: int,
        operator_id: str,
        updated_at: datetime.datetime,
    ) -> bool:
        """Change stay dates / room type, guarded by the old status."""
        cursor = conn.execute(
            "UPDATE bookings SET room_type_id = ?, check_in = ?, "
            "check_out = ?, rooms = ?, unit_price_cents = ?, "
            "total_cents = ?, updated_at = ?, operator_id = ? "
            "WHERE booking_id = ? AND status = ?",
            (
                room_type_id,
                check_in.isoformat(),
                check_out.isoformat(),
                rooms,
                unit_price_cents,
                total_cents,
                updated_at.isoformat(),
                operator_id,
                booking_id,
                expected.value,
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def count_by_status(
        conn: sqlite3.Connection,
        hotel_id: str,
        status: enums.BookingStatus,
        start: datetime.date,
        end: datetime.date,
    ) -> int:
        """Count bookings of one hotel whose stay starts in a range."""
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM bookings WHERE hotel_id = ? "
            "AND status = ? AND check_in >= ? AND check_in < ?",
            (
                hotel_id,
                status.value,
                start.isoformat(),
                end.isoformat(),
            ),
        ).fetchone()
        return int(row["total"])


def _booking_from_row(row: sqlite3.Row) -> entities.Booking:
    return entities.Booking(
        booking_id=row["booking_id"],
        customer_id=row["customer_id"],
        hotel_id=row["hotel_id"],
        room_type_id=row["room_type_id"],
        check_in=_as_date(row["check_in"]),
        check_out=_as_date(row["check_out"]),
        rooms=row["rooms"],
        unit_price_cents=row["unit_price_cents"],
        total_cents=row["total_cents"],
        status=enums.BookingStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        created_at=_as_datetime(row["created_at"]),
        updated_at=_as_datetime(row["updated_at"]),
        cancel_reason=row["cancel_reason"],
        operator_id=row["operator_id"],
    )


class LogRepository:
    """Audit log storage, query and retention (REQ-014, REQ-020)."""

    @staticmethod
    def insert(conn: sqlite3.Connection, item: entities.OperationLog) -> None:
        """Write one log row inside the business transaction."""
        conn.execute(
            "INSERT INTO logs (log_id, operator_id, operator_role, "
            "object_type, object_id, action, before_state, after_state, "
            "result, created_at, detail) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.log_id,
                item.operator_id,
                item.operator_role,
                item.object_type,
                item.object_id,
                item.action,
                item.before_state,
                item.after_state,
                item.result,
                item.created_at.isoformat(),
                item.detail,
            ),
        )

    @staticmethod
    def query(
        conn: sqlite3.Connection,
        start: datetime.date | None = None,
        end: datetime.date | None = None,
        operator_id: str = "",
        object_type: str = "",
        action: str = "",
        limit: int = 50,
    ) -> list[entities.OperationLog]:
        """Query logs by time, operator, object type and action."""
        sql = "SELECT * FROM logs WHERE 1 = 1"
        params: list[object] = []
        if start is not None:
            sql += " AND created_at >= ?"
            params.append(start.isoformat())
        if end is not None:
            sql += " AND created_at < ?"
            params.append(
                (end + datetime.timedelta(days=1)).isoformat()
            )
        if operator_id:
            sql += " AND operator_id = ?"
            params.append(operator_id)
        if object_type:
            sql += " AND object_type = ?"
            params.append(object_type)
        if action:
            sql += " AND action = ?"
            params.append(action)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [_log_from_row(row) for row in rows]

    @staticmethod
    def purge_before(
        conn: sqlite3.Connection, keep_until: datetime.datetime
    ) -> int:
        """Delete logs older than the retention window."""
        cursor = conn.execute(
            "DELETE FROM logs WHERE created_at < ?",
            (keep_until.isoformat(),),
        )
        return cursor.rowcount

    @staticmethod
    def count(conn: sqlite3.Connection) -> int:
        """Number of stored log rows, useful for tests."""
        row = conn.execute("SELECT COUNT(*) AS total FROM logs").fetchone()
        return int(row["total"])


def _log_from_row(row: sqlite3.Row) -> entities.OperationLog:
    return entities.OperationLog(
        log_id=row["log_id"],
        operator_id=row["operator_id"],
        operator_role=row["operator_role"],
        object_type=row["object_type"],
        object_id=row["object_id"],
        action=row["action"],
        before_state=row["before_state"],
        after_state=row["after_state"],
        result=row["result"],
        created_at=_as_datetime(row["created_at"]),
        detail=row["detail"],
    )


class SearchRepository:
    """Read-only joins used by the customer search page (REQ-005).

    The query requires one inventory row for every stay date
    (``HAVING COUNT(*) = nights``), so a room type with a missing or
    stopped date simply does not appear in the result list.
    """

    @staticmethod
    def search_available(
        conn: sqlite3.Connection,
        city: str,
        check_in: datetime.date,
        check_out: datetime.date,
        guests: int = 1,
        keyword: str = "",
        max_total_cents: int | None = None,
        rooms: int = 1,
    ) -> list[sqlite3.Row]:
        """Return room types that are bookable for the whole date range."""
        nights = (check_out - check_in).days
        sql = (
            "SELECT h.hotel_id, h.name AS hotel_name, h.star, "
            "r.room_type_id, r.name AS room_name, r.capacity, "
            "r.bed_type, MIN(i.available_rooms) AS min_available, "
            "SUM(i.price_cents) AS stay_total_cents "
            "FROM room_types r "
            "JOIN hotels h ON h.hotel_id = r.hotel_id "
            "JOIN inventory i ON i.room_type_id = r.room_type_id "
            "WHERE h.city = ? AND h.status = ? AND r.sale_status = ? "
            "AND i.stay_date >= ? AND i.stay_date < ? "
            "AND i.stopped = 0 AND r.capacity >= ? "
        )
        params: list[object] = [
            city,
            enums.HotelStatus.ONLINE.value,
            enums.SaleStatus.ON_SALE.value,
            check_in.isoformat(),
            check_out.isoformat(),
            guests,
        ]
        if keyword:
            sql += "AND (r.name LIKE ? OR h.name LIKE ?) "
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        sql += (
            "GROUP BY r.room_type_id "
            "HAVING COUNT(i.stay_date) = ? AND MIN(i.available_rooms) >= ? "
        )
        params.extend([nights, rooms])
        if max_total_cents is not None:
            sql += "AND SUM(i.price_cents) <= ? "
            params.append(max_total_cents)
        sql += "ORDER BY stay_total_cents ASC, h.star DESC"
        return conn.execute(sql, params).fetchall()
