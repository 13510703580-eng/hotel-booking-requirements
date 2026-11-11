"""Hotel master data and platform moderation (REQ-002, REQ-016).

Taking a hotel offline must not make confirmed bookings vanish: the
service cancels them, returns their stock and records the reason, all
inside one transaction.
"""

import datetime

from hotel_booking.data.database import Database
from hotel_booking.data.repositories import (
    BookingRepository,
    HotelRepository,
    InventoryRepository,
    RoomTypeRepository,
)
from hotel_booking.domain import entities, enums, rules
from hotel_booking.domain.errors import AppError, ErrorCode
from hotel_booking.service.auth import AuthService, Session
from hotel_booking.service.log import LogService


class HotelService:
    """Read and change hotel records."""

    def __init__(self, database: Database, logs: LogService) -> None:
        """Keep the database handle and the log writer."""
        self._db = database
        self._logs = logs

    def get(self, hotel_id: str) -> entities.Hotel:
        """Load a hotel or raise an actionable error."""
        with self._db.read() as conn:
            hotel = HotelRepository.get(conn, hotel_id)
        if hotel is None:
            raise AppError(
                ErrorCode.HOTEL_NOT_FOUND,
                reason=f"找不到酒店 {hotel_id}。",
                advice="返回酒店列表重新选择。",
                target="酒店列表",
            )
        return hotel

    def list_city(self, city: str) -> list[entities.Hotel]:
        """List online hotels of a city."""
        with self._db.read() as conn:
            return HotelRepository.list_by_city(conn, city, True)

    def update_info(
        self,
        operator: Session,
        hotel_id: str,
        name: str,
        address: str,
        star: int,
    ) -> entities.Hotel:
        """Staff update their own hotel profile."""
        AuthService.require_role(operator, enums.Role.STAFF)
        AuthService.require_hotel_scope(operator, hotel_id)
        if not name.strip() or not address.strip():
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                reason="酒店名称和地址不能为空。",
                advice="补全名称与地址后重新保存。",
                target="酒店信息维护",
            )
        if star < 1 or star > 5:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                reason="星级必须在 1 到 5 之间。",
                advice="选择 1~5 星后重新保存。",
                target="酒店信息维护",
            )
        with self._db.transaction() as conn:
            hotel = HotelRepository.get(conn, hotel_id)
            if hotel is None:
                raise AppError(ErrorCode.HOTEL_NOT_FOUND)
            HotelRepository.update_info(
                conn, hotel_id, name.strip(), address.strip(), star
            )
            self._logs.write(
                conn,
                operator,
                "HOTEL",
                hotel_id,
                enums.ActionType.UPDATE_HOTEL,
                hotel.status.value,
                hotel.status.value,
                detail=f"{name} / {address} / {star} 星",
            )
        return self.get(hotel_id)

    def update_room_type(
        self,
        operator: Session,
        room_type_id: str,
        name: str,
        capacity: int,
        bed_type: str,
        base_price_cents: int,
        sale_status: enums.SaleStatus,
    ) -> entities.RoomType:
        """Staff maintain a room type of their own hotel (REQ-003)."""
        AuthService.require_role(operator, enums.Role.STAFF)
        with self._db.read() as conn:
            room = RoomTypeRepository.get(conn, room_type_id)
        if room is None:
            raise AppError(ErrorCode.ROOM_TYPE_NOT_FOUND)
        AuthService.require_hotel_scope(operator, room.hotel_id)
        rules.validate_price(base_price_cents)
        if capacity < 1:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                reason="房型容量至少为 1 人。",
                advice="修改可住人数后重新保存。",
                target="房型与价格",
            )
        with self._db.transaction() as conn:
            RoomTypeRepository.update(
                conn,
                room_type_id,
                name.strip() or room.name,
                capacity,
                bed_type.strip() or room.bed_type,
                base_price_cents,
                sale_status,
            )
            self._logs.write(
                conn,
                operator,
                "ROOM_TYPE",
                room_type_id,
                enums.ActionType.UPDATE_HOTEL,
                f"{room.base_price_cents / 100:.2f} 元",
                f"{base_price_cents / 100:.2f} 元",
                detail=f"容量 {capacity}，床型 {bed_type}",
            )
        with self._db.read() as conn:
            refreshed = RoomTypeRepository.get(conn, room_type_id)
        assert refreshed is not None
        return refreshed

    def warn(
        self, operator: Session, hotel_id: str, reason: str
    ) -> entities.Hotel:
        """Admin warning; the hotel stays online but is flagged."""
        AuthService.require_role(operator, enums.Role.ADMIN)
        with self._db.transaction() as conn:
            hotel = HotelRepository.get(conn, hotel_id)
            if hotel is None:
                raise AppError(ErrorCode.HOTEL_NOT_FOUND)
            HotelRepository.update_status(
                conn, hotel_id, enums.HotelStatus.WARNING
            )
            self._logs.write(
                conn,
                operator,
                "HOTEL",
                hotel_id,
                enums.ActionType.WARN_HOTEL,
                hotel.status.value,
                enums.HotelStatus.WARNING.value,
                detail=f"警告原因：{reason}",
            )
        return self.get(hotel_id)

    def take_offline(
        self, operator: Session, hotel_id: str, reason: str
    ) -> dict[str, int]:
        """Admin takes a hotel offline and settles its live bookings."""
        AuthService.require_role(operator, enums.Role.ADMIN)
        cancelled = 0
        released = 0
        with self._db.transaction() as conn:
            hotel = HotelRepository.get(conn, hotel_id)
            if hotel is None:
                raise AppError(ErrorCode.HOTEL_NOT_FOUND)
            HotelRepository.update_status(
                conn, hotel_id, enums.HotelStatus.OFFLINE
            )
            live = BookingRepository.list_by_hotel(
                conn,
                hotel_id,
                (
                    enums.BookingStatus.PENDING_CONFIRM,
                    enums.BookingStatus.CONFIRMED,
                ),
            )
            for booking in live:
                for stay_date in booking.dates():
                    InventoryRepository.release(
                        conn,
                        booking.room_type_id,
                        stay_date,
                        booking.rooms,
                    )
                    released += 1
                changed = BookingRepository.update_status(
                    conn,
                    booking.booking_id,
                    booking.status,
                    enums.BookingStatus.CANCELLED,
                    operator.user_id,
                    cancel_reason=f"酒店下架：{reason}",
                )
                if changed:
                    cancelled += 1
                    self._logs.write(
                        conn,
                        operator,
                        "BOOKING",
                        booking.booking_id,
                        enums.ActionType.CANCEL_BOOKING,
                        booking.status.value,
                        enums.BookingStatus.CANCELLED.value,
                        detail=f"酒店下架联动取消，原因：{reason}",
                    )
            self._logs.write(
                conn,
                operator,
                "HOTEL",
                hotel_id,
                enums.ActionType.OFFLINE_HOTEL,
                hotel.status.value,
                enums.HotelStatus.OFFLINE.value,
                detail=(
                    f"下架原因：{reason}；取消预订 {cancelled} 条，"
                    f"回补库存 {released} 个房日"
                ),
            )
        return {"cancelled": cancelled, "released_days": released}

    def handle_closure(
        self,
        operator: Session,
        room_type_id: str,
        start: datetime.date,
        end: datetime.date,
        reason: str,
    ) -> dict[str, int]:
        """Temporary closure: stop sales and settle affected bookings."""
        AuthService.require_role(operator, enums.Role.STAFF)
        with self._db.read() as conn:
            room = RoomTypeRepository.get(conn, room_type_id)
        if room is None:
            raise AppError(ErrorCode.ROOM_TYPE_NOT_FOUND)
        AuthService.require_hotel_scope(operator, room.hotel_id)
        cancelled = 0
        with self._db.transaction() as conn:
            InventoryRepository.set_stopped(
                conn, room_type_id, start, end, True
            )
            live = BookingRepository.list_by_hotel(
                conn,
                room.hotel_id,
                (enums.BookingStatus.CONFIRMED,),
            )
            for booking in live:
                if booking.room_type_id != room_type_id:
                    continue
                overlap = [
                    day
                    for day in booking.dates()
                    if start <= day < end
                ]
                if not overlap:
                    continue
                for stay_date in booking.dates():
                    InventoryRepository.release(
                        conn, booking.room_type_id, stay_date, booking.rooms
                    )
                changed = BookingRepository.update_status(
                    conn,
                    booking.booking_id,
                    booking.status,
                    enums.BookingStatus.CANCELLED,
                    operator.user_id,
                    cancel_reason=f"酒店停业：{reason}",
                )
                if changed:
                    cancelled += 1
                    self._logs.write(
                        conn,
                        operator,
                        "BOOKING",
                        booking.booking_id,
                        enums.ActionType.CANCEL_BOOKING,
                        booking.status.value,
                        enums.BookingStatus.CANCELLED.value,
                        detail=f"停业联动取消，原因：{reason}",
                    )
            self._logs.write(
                conn,
                operator,
                "ROOM_TYPE",
                room_type_id,
                enums.ActionType.SET_INVENTORY,
                "OPEN",
                "STOPPED",
                detail=(
                    f"{start.isoformat()}~{end.isoformat()} 停业，"
                    f"取消预订 {cancelled} 条"
                ),
            )
        return {"cancelled": cancelled}
