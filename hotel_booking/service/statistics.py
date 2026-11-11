"""Statistics with a fixed, documented counting rule (REQ-015).

Rule (also printed by the CLI before showing the numbers):

* every stay date is counted separately, so a 3-night booking adds
  one to each of the three dates;
* cancelled, rejected and timeout-cancelled bookings are excluded;
* "bookings" counts all live bookings of that date, "confirmed" counts
  those already confirmed or further, "checked-in" counts guests who
  actually arrived;
* occupancy = checked-in rooms / configured rooms of that date.
"""

import dataclasses
import datetime

from hotel_booking.data.database import Database
from hotel_booking.data.repositories import (
    BookingRepository,
    InventoryRepository,
    RoomTypeRepository,
)
from hotel_booking.domain import enums
from hotel_booking.domain.errors import AppError, ErrorCode
from hotel_booking.service.auth import Session


@dataclasses.dataclass(frozen=True, slots=True)
class DailyStat:
    """Numbers of one stay date."""

    stay_date: datetime.date
    bookings: int
    confirmed: int
    checked_in: int
    rooms_sold: int
    rooms_total: int

    @property
    def occupancy(self) -> float:
        """Occupancy rate in percent, one decimal place."""
        if self.rooms_total <= 0:
            return 0.0
        return round(self.rooms_sold * 100.0 / self.rooms_total, 1)


class StatisticsService:
    """Compute daily bookings, confirmations and occupancy."""

    def __init__(self, database: Database) -> None:
        """Keep the database handle."""
        self._db = database

    def daily(
        self,
        operator: Session,
        hotel_id: str,
        start: datetime.date,
        end: datetime.date,
    ) -> list[DailyStat]:
        """Return one row per stay date in the half-open range."""
        self._check_permission(operator, hotel_id)
        if end <= start:
            raise AppError(
                ErrorCode.INVALID_DATE_RANGE,
                reason="统计的结束日期必须晚于开始日期。",
                advice="调整日期范围后重试。",
                target="统计报表",
            )
        with self._db.read() as conn:
            bookings = BookingRepository.list_by_hotel(conn, hotel_id)
            rooms_total = self._rooms_total(conn, hotel_id, start, end)
        buckets: dict[datetime.date, dict[str, int]] = {}
        day = start
        while day < end:
            buckets[day] = {
                "bookings": 0,
                "confirmed": 0,
                "checked_in": 0,
                "rooms_sold": 0,
            }
            day += datetime.timedelta(days=1)
        for booking in bookings:
            if booking.status in enums.INACTIVE_STATUSES:
                continue
            for stay_date in booking.dates():
                if stay_date not in buckets:
                    continue
                bucket = buckets[stay_date]
                bucket["bookings"] += 1
                if booking.status in (
                    enums.BookingStatus.CONFIRMED,
                    enums.BookingStatus.CHECKED_IN,
                    enums.BookingStatus.CHECKED_OUT,
                ):
                    bucket["confirmed"] += 1
                if booking.status in (
                    enums.BookingStatus.CHECKED_IN,
                    enums.BookingStatus.CHECKED_OUT,
                ):
                    bucket["checked_in"] += 1
                    bucket["rooms_sold"] += booking.rooms
        return [
            DailyStat(
                stay_date=day,
                bookings=bucket["bookings"],
                confirmed=bucket["confirmed"],
                checked_in=bucket["checked_in"],
                rooms_sold=bucket["rooms_sold"],
                rooms_total=rooms_total.get(day, 0),
            )
            for day, bucket in sorted(buckets.items())
        ]

    def summary(
        self,
        operator: Session,
        hotel_id: str,
        start: datetime.date,
        end: datetime.date,
    ) -> dict[str, float]:
        """Aggregate the daily rows into one headline figure set."""
        rows = self.daily(operator, hotel_id, start, end)
        bookings = sum(row.bookings for row in rows)
        confirmed = sum(row.confirmed for row in rows)
        checked_in = sum(row.checked_in for row in rows)
        sold = sum(row.rooms_sold for row in rows)
        total = sum(row.rooms_total for row in rows)
        return {
            "bookings": float(bookings),
            "confirmed": float(confirmed),
            "checked_in": float(checked_in),
            "occupancy": (
                0.0 if total == 0 else round(sold * 100.0 / total, 1)
            ),
            "confirm_rate": (
                0.0 if bookings == 0 else round(confirmed * 100.0 / bookings, 1)
            ),
            "check_in_rate": (
                0.0
                if confirmed == 0
                else round(checked_in * 100.0 / confirmed, 1)
            ),
        }

    def _rooms_total(
        self,
        conn,
        hotel_id: str,
        start: datetime.date,
        end: datetime.date,
    ) -> dict[datetime.date, int]:
        totals: dict[datetime.date, int] = {}
        rooms = RoomTypeRepository.list_by_hotel(conn, hotel_id)
        for day_offset in range((end - start).days):
            day = start + datetime.timedelta(days=day_offset)
            total = 0
            for room in rooms:
                row = InventoryRepository.get(conn, room.room_type_id, day)
                if row is not None and not row.stopped:
                    total += row.total_rooms
            totals[day] = total
        return totals

    @staticmethod
    def _check_permission(operator: Session, hotel_id: str) -> None:
        if operator.role is enums.Role.ADMIN:
            return
        if operator.role is enums.Role.STAFF:
            if operator.user.hotel_id != hotel_id:
                raise AppError(
                    ErrorCode.FORBIDDEN,
                    reason="只能统计本酒店的预订数据。",
                    advice="切换到所属酒店后再查看。",
                    target="统计报表",
                )
            return
        raise AppError(
            ErrorCode.FORBIDDEN,
            reason="顾客账号不能查看经营统计。",
            advice="使用工作人员或管理员账号登录。",
            target="登录页",
        )
