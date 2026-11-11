"""Booking life cycle: create, modify, cancel, confirm, check in/out.

The service is the transaction boundary.  One call may touch the
booking row, several inventory rows and the audit log; the database
wrapper commits them together, so REQ-020 ("business data and log
succeed or fail together") is enforced by construction rather than by
convention.
"""

import dataclasses
import datetime
import uuid

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

#: A pending booking that nobody confirms within this window expires.
CONFIRM_TIMEOUT_HOURS = 24


@dataclasses.dataclass(frozen=True, slots=True)
class CreateResult:
    """Outcome of a create request, including the idempotent replay flag."""

    booking: entities.Booking
    replayed: bool


class BookingService:
    """Every state change of a booking goes through this class."""

    def __init__(self, database: Database, logs: LogService) -> None:
        """Keep the database handle and the log writer."""
        self._db = database
        self._logs = logs

    # ------------------------------------------------------------------
    # customer operations
    # ------------------------------------------------------------------
    def create(
        self,
        operator: Session,
        room_type_id: str,
        check_in: datetime.date,
        check_out: datetime.date,
        rooms: int,
        idempotency_key: str,
    ) -> CreateResult:
        """Create a pending booking and take stock for every night."""
        AuthService.require_role(operator, enums.Role.CUSTOMER)
        rules.validate_date_range(check_in, check_out)
        rules.validate_rooms(rooms)
        if not idempotency_key:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                reason="缺少幂等键，无法安全提交。",
                advice="刷新页面后重新提交。",
                target="预订面板",
            )
        with self._db.transaction() as conn:
            existing = BookingRepository.get_by_key(conn, idempotency_key)
            if existing is not None:
                if existing.customer_id != operator.user_id:
                    raise AppError(
                        ErrorCode.FORBIDDEN,
                        reason="该幂等键已被其他账号使用。",
                        advice="刷新页面重新提交一次。",
                        target="预订面板",
                    )
                return CreateResult(booking=existing, replayed=True)
            room = self._require_room(conn, room_type_id)
            hotel = self._require_bookable_hotel(conn, room.hotel_id)
            dates = self._dates(check_in, check_out)
            stay_prices = self._reserve(conn, room_type_id, dates, rooms)
            total = sum(stay_prices) * rooms
            now = datetime.datetime.now()
            booking = entities.Booking(
                booking_id=f"B{uuid.uuid4().hex[:10]}",
                customer_id=operator.user_id,
                hotel_id=hotel.hotel_id,
                room_type_id=room_type_id,
                check_in=check_in,
                check_out=check_out,
                rooms=rooms,
                unit_price_cents=total // (len(dates) * rooms),
                total_cents=total,
                status=enums.BookingStatus.PENDING_CONFIRM,
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
            )
            BookingRepository.insert(conn, booking)
            self._logs.write(
                conn,
                operator,
                "BOOKING",
                booking.booking_id,
                enums.ActionType.CREATE_BOOKING,
                "",
                enums.BookingStatus.PENDING_CONFIRM.value,
                detail=(
                    f"{room.name} {check_in.isoformat()}~"
                    f"{check_out.isoformat()} x{rooms} 间 "
                    f"金额 {total / 100:.2f} 元"
                ),
            )
            return CreateResult(booking=booking, replayed=False)

    def modify(
        self,
        operator: Session,
        booking_id: str,
        check_in: datetime.date,
        check_out: datetime.date,
        rooms: int = 0,
        room_type_id: str = "",
    ) -> entities.Booking:
        """Change dates or room type and re-check the stock."""
        AuthService.require_role(
            operator, enums.Role.CUSTOMER, enums.Role.STAFF
        )
        rules.validate_date_range(check_in, check_out)
        with self._db.transaction() as conn:
            booking = self._require_booking(conn, booking_id)
            self._check_scope(operator, booking)
            if booking.status not in rules.CUSTOMER_EDITABLE:
                raise AppError(
                    ErrorCode.STATE_NOT_ALLOWED,
                    reason=(
                        "当前状态为"
                        f"“{rules.status_label(booking.status)}”，不能修改。"
                    ),
                    advice="已入住或已取消的预订不能改期，如需变更请新建预订。",
                    target="我的预订",
                )
            new_rooms = rooms or booking.rooms
            rules.validate_rooms(new_rooms)
            new_room_type = room_type_id or booking.room_type_id
            room = self._require_room(conn, new_room_type)
            self._require_bookable_hotel(conn, room.hotel_id)
            self._release(conn, booking)
            try:
                dates = self._dates(check_in, check_out)
                stay_prices = self._reserve(
                    conn, new_room_type, dates, new_rooms
                )
            except AppError:
                # The transaction will roll back, but re-raise with a
                # hint that the original booking is untouched.
                raise AppError(
                    ErrorCode.NO_INVENTORY,
                    reason="新日期或新房型库存不足，修改未生效。",
                    advice="原预订保持不变，可选择其他日期后重试。",
                    target="我的预订",
                ) from None
            total = sum(stay_prices) * new_rooms
            updated = BookingRepository.update_stay(
                conn,
                booking_id,
                booking.status,
                new_room_type,
                check_in,
                check_out,
                new_rooms,
                total // (len(dates) * new_rooms),
                total,
                operator.user_id,
                datetime.datetime.now(),
            )
            if not updated:
                raise AppError(
                    ErrorCode.STATE_NOT_ALLOWED,
                    reason="预订状态在提交过程中发生变化，修改已取消。",
                    advice="刷新订单查看最新状态后再操作。",
                    target="我的预订",
                )
            self._logs.write(
                conn,
                operator,
                "BOOKING",
                booking_id,
                enums.ActionType.MODIFY_BOOKING,
                f"{booking.check_in}~{booking.check_out}",
                f"{check_in}~{check_out}",
                detail=f"金额 {total / 100:.2f} 元，间数 {new_rooms}",
            )
            refreshed = BookingRepository.get(conn, booking_id)
            assert refreshed is not None
            return refreshed

    def cancel(
        self, operator: Session, booking_id: str, reason: str
    ) -> entities.Booking:
        """Cancel a pending or confirmed booking and return the stock."""
        AuthService.require_role(
            operator, enums.Role.CUSTOMER, enums.Role.STAFF
        )
        with self._db.transaction() as conn:
            booking = self._require_booking(conn, booking_id)
            self._check_scope(operator, booking)
            if booking.status is enums.BookingStatus.CANCELLED:
                return booking
            if booking.status not in rules.CUSTOMER_EDITABLE:
                raise AppError(
                    ErrorCode.STATE_NOT_ALLOWED,
                    reason=(
                        "当前状态为"
                        f"“{rules.status_label(booking.status)}”，不能取消。"
                    ),
                    advice="已入住或已离店的预订需联系酒店前台处理。",
                    target="我的预订",
                )
            self._release(conn, booking)
            changed = BookingRepository.update_status(
                conn,
                booking_id,
                booking.status,
                enums.BookingStatus.CANCELLED,
                operator.user_id,
                cancel_reason=reason or "用户取消",
            )
            if not changed:
                raise AppError(
                    ErrorCode.STATE_NOT_ALLOWED,
                    reason="预订状态已变化，取消未生效。",
                    advice="刷新订单后重试。",
                    target="我的预订",
                )
            self._logs.write(
                conn,
                operator,
                "BOOKING",
                booking_id,
                enums.ActionType.CANCEL_BOOKING,
                booking.status.value,
                enums.BookingStatus.CANCELLED.value,
                detail=f"原因：{reason or '未填写'}",
            )
            refreshed = BookingRepository.get(conn, booking_id)
            assert refreshed is not None
            return refreshed

    def list_mine(self, operator: Session) -> list[entities.Booking]:
        """Return the bookings of the logged-in customer."""
        AuthService.require_role(operator, enums.Role.CUSTOMER)
        with self._db.read() as conn:
            return BookingRepository.list_by_customer(
                conn, operator.user_id
            )

    def get(self, operator: Session, booking_id: str) -> entities.Booking:
        """Load one booking after checking the data scope."""
        with self._db.read() as conn:
            booking = self._require_booking(conn, booking_id)
        self._check_scope(operator, booking)
        return booking

    # ------------------------------------------------------------------
    # hotel staff operations
    # ------------------------------------------------------------------
    def confirm(
        self, operator: Session, booking_id: str
    ) -> entities.Booking:
        """Confirm a pending booking of the operator's hotel."""
        return self._staff_transition(
            operator,
            booking_id,
            enums.BookingStatus.CONFIRMED,
            enums.ActionType.CONFIRM_BOOKING,
            "确认预订",
        )

    def reject(
        self, operator: Session, booking_id: str, reason: str
    ) -> entities.Booking:
        """Reject a pending booking and return its stock."""
        AuthService.require_role(operator, enums.Role.STAFF)
        with self._db.transaction() as conn:
            booking = self._require_booking(conn, booking_id)
            AuthService.require_hotel_scope(operator, booking.hotel_id)
            if booking.status is enums.BookingStatus.REJECTED:
                return booking
            rules.require_transition(
                booking.status, enums.BookingStatus.REJECTED
            )
            self._release(conn, booking)
            changed = BookingRepository.update_status(
                conn,
                booking_id,
                booking.status,
                enums.BookingStatus.REJECTED,
                operator.user_id,
                cancel_reason=reason or "酒店拒绝",
            )
            if not changed:
                raise AppError(
                    ErrorCode.STATE_NOT_ALLOWED,
                    reason="预订状态已变化，拒绝未生效。",
                    advice="刷新列表后重试。",
                    target="预订管理",
                )
            self._logs.write(
                conn,
                operator,
                "BOOKING",
                booking_id,
                enums.ActionType.REJECT_BOOKING,
                booking.status.value,
                enums.BookingStatus.REJECTED.value,
                detail=f"原因：{reason or '未填写'}",
            )
            refreshed = BookingRepository.get(conn, booking_id)
            assert refreshed is not None
            return refreshed

    def check_in(
        self, operator: Session, booking_id: str
    ) -> entities.Booking:
        """Turn a confirmed booking into a checked-in one."""
        return self._staff_transition(
            operator,
            booking_id,
            enums.BookingStatus.CHECKED_IN,
            enums.ActionType.CHECK_IN,
            "办理入住",
        )

    def check_out(
        self, operator: Session, booking_id: str
    ) -> entities.Booking:
        """Turn a checked-in booking into a checked-out one."""
        return self._staff_transition(
            operator,
            booking_id,
            enums.BookingStatus.CHECKED_OUT,
            enums.ActionType.CHECK_OUT,
            "办理退房",
        )

    def list_hotel(
        self,
        operator: Session,
        statuses: tuple[enums.BookingStatus, ...] | None = None,
    ) -> list[entities.Booking]:
        """List bookings of the staff's own hotel."""
        AuthService.require_role(operator, enums.Role.STAFF)
        hotel_id = operator.user.hotel_id
        if not hotel_id:
            raise AppError(
                ErrorCode.FORBIDDEN,
                reason="该工作人员账号未绑定酒店。",
                advice="联系管理员补充所属酒店。",
                target="客服",
            )
        with self._db.read() as conn:
            return BookingRepository.list_by_hotel(
                conn, hotel_id, statuses
            )

    def _staff_transition(
        self,
        operator: Session,
        booking_id: str,
        target: enums.BookingStatus,
        action: enums.ActionType,
        label: str,
    ) -> entities.Booking:
        AuthService.require_role(operator, enums.Role.STAFF)
        with self._db.transaction() as conn:
            booking = self._require_booking(conn, booking_id)
            AuthService.require_hotel_scope(operator, booking.hotel_id)
            if booking.status is target:
                # Repeated check-in / confirm returns the original result.
                return booking
            rules.require_transition(booking.status, target)
            changed = BookingRepository.update_status(
                conn,
                booking_id,
                booking.status,
                target,
                operator.user_id,
            )
            if not changed:
                raise AppError(
                    ErrorCode.STATE_NOT_ALLOWED,
                    reason=f"{label}失败：预订状态已变化。",
                    advice="刷新订单列表后重试。",
                    target="预订管理",
                )
            self._logs.write(
                conn,
                operator,
                "BOOKING",
                booking_id,
                action,
                booking.status.value,
                target.value,
                detail=label,
            )
            refreshed = BookingRepository.get(conn, booking_id)
            assert refreshed is not None
            return refreshed

    # ------------------------------------------------------------------
    # scheduled task
    # ------------------------------------------------------------------
    def sweep_timeout(self, now: datetime.datetime | None = None) -> int:
        """Cancel pending bookings older than the confirm window."""
        moment = now or datetime.datetime.now()
        deadline = moment - datetime.timedelta(hours=CONFIRM_TIMEOUT_HOURS)
        expired = 0
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT booking_id FROM bookings WHERE status = ? "
                "AND created_at < ?",
                (
                    enums.BookingStatus.PENDING_CONFIRM.value,
                    deadline.isoformat(),
                ),
            ).fetchall()
        for row in rows:
            booking_id = row["booking_id"]
            with self._db.transaction() as conn:
                booking = BookingRepository.get(conn, booking_id)
                if booking is None:
                    continue
                if booking.status is not enums.BookingStatus.PENDING_CONFIRM:
                    continue
                self._release(conn, booking)
                changed = BookingRepository.update_status(
                    conn,
                    booking_id,
                    enums.BookingStatus.PENDING_CONFIRM,
                    enums.BookingStatus.TIMEOUT_CANCELLED,
                    "SYSTEM",
                    cancel_reason="超过确认时限自动取消",
                )
                if changed:
                    self._logs.write(
                        conn,
                        None,
                        "BOOKING",
                        booking_id,
                        enums.ActionType.CANCEL_BOOKING,
                        enums.BookingStatus.PENDING_CONFIRM.value,
                        enums.BookingStatus.TIMEOUT_CANCELLED.value,
                        detail="定时任务：超时未确认",
                    )
                    expired += 1
        return expired

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _dates(
        check_in: datetime.date, check_out: datetime.date
    ) -> list[datetime.date]:
        return [
            check_in + datetime.timedelta(days=offset)
            for offset in range((check_out - check_in).days)
        ]

    @staticmethod
    def _require_room(conn, room_type_id: str) -> entities.RoomType:
        room = RoomTypeRepository.get(conn, room_type_id)
        if room is None:
            raise AppError(
                ErrorCode.ROOM_TYPE_NOT_FOUND,
                reason="该房型不存在。",
                advice="返回列表重新选择房型。",
                target="查询可订房型",
            )
        if room.sale_status is not enums.SaleStatus.ON_SALE:
            raise AppError(
                ErrorCode.ROOM_TYPE_OFF_SALE,
                reason="该房型已停售。",
                advice="选择同酒店其他房型。",
                target="查询可订房型",
            )
        return room

    @staticmethod
    def _require_bookable_hotel(conn, hotel_id: str) -> entities.Hotel:
        hotel = HotelRepository.get(conn, hotel_id)
        if hotel is None:
            raise AppError(ErrorCode.HOTEL_NOT_FOUND)
        if not hotel.is_bookable():
            raise AppError(
                ErrorCode.HOTEL_OFFLINE,
                reason=f"“{hotel.name}”当前已下架或整改中。",
                advice="选择同城其他酒店。",
                target="查询可订房型",
            )
        return hotel

    @staticmethod
    def _require_booking(conn, booking_id: str) -> entities.Booking:
        booking = BookingRepository.get(conn, booking_id)
        if booking is None:
            raise AppError(
                ErrorCode.BOOKING_NOT_FOUND,
                reason=f"找不到预订 {booking_id}。",
                advice="确认订单编号，或在“我的预订”中查看。",
                target="我的预订",
            )
        return booking

    def _reserve(
        self,
        conn,
        room_type_id: str,
        dates: list[datetime.date],
        rooms: int,
    ) -> list[int]:
        """Take stock for each date, returning the nightly prices."""
        prices: list[int] = []
        for stay_date in dates:
            row = InventoryRepository.get(conn, room_type_id, stay_date)
            if row is None:
                raise AppError(
                    ErrorCode.NO_INVENTORY,
                    reason=f"{stay_date.isoformat()} 尚未开放预订。",
                    advice="该日期暂未设置库存，请选择其他日期。",
                    target="查询可订房型",
                )
            if not InventoryRepository.try_reserve(
                conn, room_type_id, stay_date, rooms
            ):
                raise rules.describe_shortage(
                    stay_date,
                    rooms,
                    row.sellable_rooms(),
                    row.stopped,
                )
            prices.append(row.price_cents)
        return prices

    @staticmethod
    def _release(conn, booking: entities.Booking) -> None:
        """Give every night of the booking back, exactly once."""
        for stay_date in booking.dates():
            InventoryRepository.release(
                conn, booking.room_type_id, stay_date, booking.rooms
            )

    @staticmethod
    def _check_scope(operator: Session, booking: entities.Booking) -> None:
        if operator.role is enums.Role.ADMIN:
            return
        if operator.role is enums.Role.CUSTOMER:
            if booking.customer_id != operator.user_id:
                raise AppError(
                    ErrorCode.FORBIDDEN,
                    reason="这条预订不属于当前账号。",
                    advice="回到“我的预订”查看自己的订单。",
                    target="我的预订",
                )
            return
        AuthService.require_hotel_scope(operator, booking.hotel_id)
