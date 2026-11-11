"""Authentication, password hashing and authorization (REQ-001/019).

Passwords are stored as PBKDF2-HMAC-SHA256 with a random salt, never
in plain text.  A session is a small value object holding the user and
the moment of login; services accept it instead of a bare user id so
that "not logged in" and "wrong role" are two distinct errors.
"""

import dataclasses
import datetime
import hashlib
import hmac
import secrets
import uuid

from hotel_booking.data.database import Database
from hotel_booking.data.repositories import UserRepository
from hotel_booking.domain import entities, enums
from hotel_booking.domain.errors import AppError, ErrorCode

_ITERATIONS = 120_000
_SALT_BYTES = 16
_MIN_PASSWORD_LENGTH = 8


@dataclasses.dataclass(frozen=True, slots=True)
class Session:
    """A logged-in actor and the moment the session was created."""

    user: entities.User
    issued_at: datetime.datetime

    @property
    def role(self) -> enums.Role:
        """Shortcut to the role of the logged-in user."""
        return self.user.role

    @property
    def user_id(self) -> str:
        """Shortcut to the identifier of the logged-in user."""
        return self.user.user_id


def hash_password(password: str) -> str:
    """Return a salted PBKDF2 hash in ``algorithm$iterations$salt$hash``."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _ITERATIONS
    )
    return (
        f"pbkdf2_sha256${_ITERATIONS}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against a stored hash."""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def validate_password(password: str) -> None:
    """Enforce a minimal password policy before hashing."""
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            reason="密码至少需要 8 位。",
            advice="使用 8 位以上、同时包含字母和数字的密码。",
            target="注册表单",
        )
    if not any(char.isdigit() for char in password):
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            reason="密码需要包含数字。",
            advice="在密码中加入数字后重新提交。",
            target="注册表单",
        )


class AuthService:
    """Registration, login and the permission checks used by services."""

    def __init__(self, database: Database) -> None:
        """Store the database handle used for every account operation."""
        self._db = database

    def register_customer(
        self,
        phone: str,
        password: str,
        display_name: str,
    ) -> entities.User:
        """Self-service registration of a customer account."""
        return self._register(
            phone=phone,
            password=password,
            role=enums.Role.CUSTOMER,
            display_name=display_name,
            hotel_id=None,
        )

    def create_staff_account(
        self,
        operator: Session,
        phone: str,
        password: str,
        display_name: str,
        hotel_id: str,
    ) -> entities.User:
        """Admin-only creation of a hotel staff account (REQ-001)."""
        self.require_role(operator, enums.Role.ADMIN)
        return self._register(
            phone=phone,
            password=password,
            role=enums.Role.STAFF,
            display_name=display_name,
            hotel_id=hotel_id,
        )

    def _register(
        self,
        phone: str,
        password: str,
        role: enums.Role,
        display_name: str,
        hotel_id: str | None,
    ) -> entities.User:
        if not phone.isdigit() or len(phone) != 11:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                reason="手机号必须是 11 位数字。",
                advice="检查手机号后重新输入。",
                target="注册表单",
            )
        validate_password(password)
        user = entities.User(
            user_id=f"U{uuid.uuid4().hex[:10]}",
            phone=phone,
            password_hash=hash_password(password),
            role=role,
            display_name=display_name.strip() or phone,
            hotel_id=hotel_id,
        )
        with self._db.transaction() as conn:
            UserRepository.insert(conn, user, datetime.datetime.now())
        return user

    def login(self, phone: str, password: str) -> Session:
        """Verify the credentials and return a session."""
        with self._db.read() as conn:
            user = UserRepository.get_by_phone(conn, phone)
        if user is None or not verify_password(password, user.password_hash):
            raise AppError(
                ErrorCode.INVALID_CREDENTIALS,
                reason="手机号或密码不正确。",
                advice="确认手机号，并检查大小写后重新输入。",
                target="登录页",
            )
        if not user.enabled:
            raise AppError(
                ErrorCode.ACCOUNT_DISABLED,
                reason="该账号已被平台停用。",
                advice="联系平台管理员核实账号状态。",
                target="客服",
            )
        return Session(user=user, issued_at=datetime.datetime.now())

    @staticmethod
    def require_login(operator: Session | None) -> Session:
        """Reject anonymous callers with the "go and log in" hint."""
        if operator is None:
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                reason="尚未登录，无法执行该操作。",
                advice="先用手机号和密码登录。",
                target="登录页",
            )
        return operator

    @staticmethod
    def require_role(
        operator: Session, *roles: enums.Role
    ) -> None:
        """Reject a caller whose role is not one of ``roles``."""
        if operator is None:
            raise AppError(ErrorCode.AUTH_REQUIRED)
        if operator.role not in roles:
            raise AppError(
                ErrorCode.FORBIDDEN,
                reason="当前角色没有这项操作的权限。",
                advice="切换到具备权限的账号（工作人员或管理员）。",
                target="工作台",
            )

    @staticmethod
    def require_hotel_scope(operator: Session, hotel_id: str) -> None:
        """Staff may only touch their own hotel (REQ-001/019)."""
        if operator.role is enums.Role.ADMIN:
            return
        if operator.role is not enums.Role.STAFF:
            raise AppError(
                ErrorCode.FORBIDDEN,
                reason="只有酒店工作人员可以维护酒店数据。",
                advice="使用所属酒店的工作人员账号登录。",
                target="登录页",
            )
        if operator.user.hotel_id != hotel_id:
            raise AppError(
                ErrorCode.FORBIDDEN,
                reason="这条数据属于其他酒店，当前账号无权操作。",
                advice="回到本酒店工作台，只处理本酒店的房型与预订。",
                target="酒店工作台",
            )
