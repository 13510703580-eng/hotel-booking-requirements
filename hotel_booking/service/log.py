"""Audit logging service (REQ-014, REQ-019, REQ-020).

The service deliberately exposes a ``write`` method that takes an open
connection: the caller writes the log inside the same transaction as
the business change, which is how "booking, stock and log succeed or
fail together" is implemented.

``fail_next_write`` exists to simulate a broken log writer in tests
(the requirement asks that a failed log write rolls the business
operation back).
"""

import datetime
import uuid

from hotel_booking.data.database import Database
from hotel_booking.data.repositories import LogRepository
from hotel_booking.domain import entities, enums
from hotel_booking.domain.errors import AppError, ErrorCode
from hotel_booking.service.auth import Session


class LogService:
    """Create, query and purge operation logs."""

    def __init__(self, database: Database) -> None:
        """Keep the database handle and reset the fault injection flag."""
        self._db = database
        self.fail_next_write = False

    def write(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        conn,
        operator: Session | None,
        object_type: str,
        object_id: str,
        action: enums.ActionType,
        before_state: str,
        after_state: str,
        result: str = "SUCCESS",
        detail: str = "",
    ) -> entities.OperationLog:
        """Insert one log row on the caller's connection."""
        if self.fail_next_write:
            self.fail_next_write = False
            raise AppError(
                ErrorCode.LOG_WRITE_FAILED,
                reason="操作日志写入失败（模拟故障），业务操作已回滚。",
                advice="稍后重试；若持续失败请联系管理员。",
                target="重新提交操作",
            )
        log = entities.OperationLog(
            log_id=f"L{uuid.uuid4().hex[:10]}",
            operator_id="anonymous" if operator is None else operator.user_id,
            operator_role=(
                "ANONYMOUS" if operator is None else operator.role.value
            ),
            object_type=object_type,
            object_id=object_id,
            action=action.value,
            before_state=before_state,
            after_state=after_state,
            result=result,
            created_at=datetime.datetime.now(),
            detail=detail,
        )
        LogRepository.insert(conn, log)
        return log

    def query(
        self,
        operator: Session,
        start: datetime.date | None = None,
        end: datetime.date | None = None,
        operator_id: str = "",
        object_type: str = "",
        action: str = "",
        limit: int = 50,
    ) -> list[entities.OperationLog]:
        """Admin-only log search by time, actor, object and action."""
        if operator.role is not enums.Role.ADMIN:
            raise AppError(
                ErrorCode.FORBIDDEN,
                reason="只有平台管理员可以查询操作日志。",
                advice="使用管理员账号登录后重试。",
                target="登录页",
            )
        with self._db.read() as conn:
            return LogRepository.query(
                conn,
                start=start,
                end=end,
                operator_id=operator_id,
                object_type=object_type,
                action=action,
                limit=limit,
            )

    def count(self) -> int:
        """Return how many log rows are stored (used by tests)."""
        with self._db.read() as conn:
            return LogRepository.count(conn)

    def purge_expired(self, keep_days: int = 180) -> int:
        """Drop rows older than the retention window of REQ-020."""
        cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
        with self._db.transaction() as conn:
            return LogRepository.purge_before(conn, cutoff)
