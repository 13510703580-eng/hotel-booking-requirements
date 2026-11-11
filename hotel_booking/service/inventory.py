"""Daily inventory management and customer search (REQ-004/005).

All stock mutations go through the conditional UPDATE of
``InventoryRepository``; this service only validates the input,
resolves ownership (staff may only change their own hotel) and writes
the audit log in the same transaction.
"""

import dataclasses
import datetime
from typing import Optional

from hotel_booking.data.database import Database
from hotel_booking.data.repositories import (
    HotelRepository,
    InventoryRepository,
    RoomTypeRepository,
    SearchRepository,
)
from hotel_booking.domain import entities, enums, rules
from hotel_booking.domain.errors import AppError, ErrorCode
from hotel_booking.service.auth import AuthService, Session
from hotel_booking.service.log import LogService


@dataclasses.dataclass(frozen=True, slots=True)
class SearchHit:
    """One bookable room type shown to the customer."""

    hotel_id: str
    hotel_name: str
    star: int
    room_type_id: str
    room_name: str
    capacity: int
    bed_type: str
    available_rooms: int
    stay_total_cents: int

    def nightly_cents(self, nights: int) -> int:
        """Average price per room per night, for display."""
        return self.stay_total_cents // max(nights, 1)


class InventoryService:
    """Set daily stock and search bookable room types."""

    def __init__(self, database: Database, logs: LogService) -> None:
        """Keep the database handle and the log writer."""
        self._db = database
        self._logs = logs

    def set_daily_inventory(
        self,
        operator: Session,
        room_type_id: str,
        stay_date: datetime.date,
        total_rooms: int,
        price_cents: int,
        stopped: bool = False,
    ) -> entities.DailyInventory:
        """Create or update one date's stock for a room type."""
        if total_rooms < 0:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                reason="每日可售数量不能为负数。",
                advice="填写 0 或正整数。",
                target="每日库存与停售",
            )
        rules.validate_price(price_cents)
        room, hotel_id = self._require_own_room(operator, room_type_id)
        item = entities.DailyInventory(
            room_type_id=room_type_id,
            stay_date=stay_date,
            total_rooms=total_rooms,
            available_rooms=total_rooms,
            price_cents=price_cents,
            stopped=stopped,
        )
        with self._db.transaction() as conn:
            InventoryRepository.upsert(conn, item)
            self._logs.write(
                conn,
                operator,
                "ROOM_TYPE",
                room_type_id,
                enums.ActionType.SET_INVENTORY,
                "UNKNOWN",
                (
                    f"{stay_date.isoformat()} total={total_rooms} "
                    f"price={price_cents} stopped={stopped}"
                ),
                detail=f"酒店 {hotel_id} 房型 {room.name}",
            )
        return item

    def bulk_set(
        self,
        operator: Session,
        room_type_id: str,
        start: datetime.date,
        end: datetime.date,
        total_rooms: int,
        price_cents: int,
        stopped: bool = False,
    ) -> int:
        """Apply the same stock settings to a date range."""
        if end <= start:
            raise AppError(
                ErrorCode.INVALID_DATE_RANGE,
                reason="结束日期必须晚于开始日期。",
                advice="调整日期范围后重试。",
                target="批量设置",
            )
        self._require_own_room(operator, room_type_id)
        count = 0
        with self._db.transaction() as conn:
            day = start
            while day < end:
                InventoryRepository.upsert(
                    conn,
                    entities.DailyInventory(
                        room_type_id=room_type_id,
                        stay_date=day,
                        total_rooms=total_rooms,
                        available_rooms=total_rooms,
                        price_cents=price_cents,
                        stopped=stopped,
                    ),
                )
                count += 1
                day += datetime.timedelta(days=1)
            self._logs.write(
                conn,
                operator,
                "ROOM_TYPE",
                room_type_id,
                enums.ActionType.SET_INVENTORY,
                "UNKNOWN",
                f"{start.isoformat()}~{end.isoformat()} days={count}",
                detail="批量设置每日库存",
            )
        return count

    def set_stopped(
        self,
        operator: Session,
        room_type_id: str,
        start: datetime.date,
        end: datetime.date,
        stopped: bool,
    ) -> int:
        """Stop or resume sales for a date range (REQ-012).

        Existing confirmed bookings are *not* silently dropped; the
        caller must handle them through the booking service.
        """
        self._require_own_room(operator, room_type_id)
        with self._db.transaction() as conn:
            affected = InventoryRepository.set_stopped(
                conn, room_type_id, start, end, stopped
            )
            self._logs.write(
                conn,
                operator,
                "ROOM_TYPE",
                room_type_id,
                enums.ActionType.SET_INVENTORY,
                "OPEN",
                "STOPPED" if stopped else "OPEN",
                detail=(
                    f"{start.isoformat()}~{end.isoformat()} "
                    f"受影响 {affected} 天"
                ),
            )
        return affected

    def search(
        self,
        city: str,
        check_in: datetime.date,
        check_out: datetime.date,
        guests: int = 1,
        keyword: str = "",
        max_total_cents: Optional[int] = None,
        rooms: int = 1,
    ) -> list[SearchHit]:
        """Multi-condition search returning only bookable room types."""
        if not city.strip():
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                reason="请填写目的地城市。",
                advice="输入城市名，例如“南京”。",
                target="查询条件",
            )
        rules.validate_date_range(check_in, check_out)
        rules.validate_rooms(rooms)
        if guests < 1:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                reason="入住人数至少为 1。",
                advice="调整人数后重新查询。",
                target="查询条件",
            )
        with self._db.read() as conn:
            rows = SearchRepository.search_available(
                conn,
                city=city.strip(),
                check_in=check_in,
                check_out=check_out,
                guests=guests,
                keyword=keyword.strip(),
                max_total_cents=max_total_cents,
                rooms=rooms,
            )
        return [
            SearchHit(
                hotel_id=row["hotel_id"],
                hotel_name=row["hotel_name"],
                star=row["star"],
                room_type_id=row["room_type_id"],
                room_name=row["room_name"],
                capacity=row["capacity"],
                bed_type=row["bed_type"],
                available_rooms=row["min_available"],
                stay_total_cents=row["stay_total_cents"],
            )
            for row in rows
        ]

    def stock_of(
        self, room_type_id: str, stay_date: datetime.date
    ) -> Optional[entities.DailyInventory]:
        """Return the stock row of one date, or None when not configured."""
        with self._db.read() as conn:
            return InventoryRepository.get(conn, room_type_id, stay_date)

    def range_stock(
        self,
        room_type_id: str,
        check_in: datetime.date,
        check_out: datetime.date,
    ) -> list[entities.DailyInventory]:
        """Return all stock rows of a stay range."""
        with self._db.read() as conn:
            return InventoryRepository.list_range(
                conn, room_type_id, check_in, check_out
            )

    def _require_own_room(
        self, operator: Session, room_type_id: str
    ) -> tuple[entities.RoomType, str]:
        AuthService.require_role(operator, enums.Role.STAFF)
        with self._db.read() as conn:
            room = RoomTypeRepository.get(conn, room_type_id)
        if room is None:
            raise AppError(
                ErrorCode.ROOM_TYPE_NOT_FOUND,
                reason="房型不存在，可能已被删除。",
                advice="返回房型列表重新选择。",
                target="房型与价格",
            )
        hotel = None
        with self._db.read() as conn:
            hotel = HotelRepository.get(conn, room.hotel_id)
        if hotel is None:
            raise AppError(ErrorCode.HOTEL_NOT_FOUND)
        AuthService.require_hotel_scope(operator, hotel.hotel_id)
        return room, hotel.hotel_id
