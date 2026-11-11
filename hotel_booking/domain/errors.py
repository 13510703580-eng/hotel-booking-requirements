"""Business errors with actionable messages (REQ-021).

Every failure that a user can trigger carries three pieces of
information instead of a bare "failed":

* ``reason``  - what went wrong, in plain language;
* ``advice``  - the next step the user can take;
* ``target``  - where to go in the interface.

``AppError`` is the only exception type that crosses the service
boundary, so the CLI (or a future web layer) can render a uniform
"reason - advice - target" hint.
"""

import enum


class ErrorCode(enum.Enum):
    """Stable error codes shared by services, logs and the UI."""

    VALIDATION_FAILED = "E1001"
    INVALID_DATE_RANGE = "E1002"
    HOTEL_NOT_FOUND = "E1003"
    ROOM_TYPE_NOT_FOUND = "E1004"
    BOOKING_NOT_FOUND = "E1005"

    AUTH_REQUIRED = "E2001"
    INVALID_CREDENTIALS = "E2002"
    FORBIDDEN = "E2003"
    ACCOUNT_EXISTS = "E2004"
    ACCOUNT_DISABLED = "E2005"

    HOTEL_OFFLINE = "E3001"
    ROOM_TYPE_OFF_SALE = "E3002"
    STOPPED_FOR_SALE = "E3003"
    NO_INVENTORY = "E3004"
    INVENTORY_CONFLICT = "E3005"
    PRICE_INVALID = "E3006"

    STATE_NOT_ALLOWED = "E4001"
    DUPLICATE_OPERATION = "E4002"
    IDEMPOTENT_REPLAY = "E4003"

    LOG_WRITE_FAILED = "E5001"

    INTERNAL_ERROR = "E9000"


#: Default advice for each error code.  Services may override the
#: advice when the situation needs a more specific suggestion.
_ADVICE: dict[ErrorCode, tuple[str, str]] = {
    ErrorCode.VALIDATION_FAILED: (
        "填写的内容不符合要求，请按提示修改后重试。",
        "返回表单",
    ),
    ErrorCode.INVALID_DATE_RANGE: (
        "离店日期必须晚于入住日期，且入住日期不能早于今天。",
        "重新选择日期",
    ),
    ErrorCode.HOTEL_NOT_FOUND: (
        "该酒店已不存在或已被下架，无法继续操作。",
        "返回酒店列表",
    ),
    ErrorCode.ROOM_TYPE_NOT_FOUND: (
        "该房型已不存在，可能已被酒店下架。",
        "返回房型列表",
    ),
    ErrorCode.BOOKING_NOT_FOUND: (
        "没有找到这条预订，可能编号有误或已被删除。",
        "返回我的预订",
    ),
    ErrorCode.AUTH_REQUIRED: (
        "当前操作需要登录后才能完成。",
        "前往登录",
    ),
    ErrorCode.INVALID_CREDENTIALS: (
        "账号或密码不正确，请核对后重试。",
        "重新输入账号密码",
    ),
    ErrorCode.FORBIDDEN: (
        "当前账号没有这项权限，或该数据不属于你。",
        "返回工作台",
    ),
    ErrorCode.ACCOUNT_EXISTS: (
        "该手机号已经注册过账号。",
        "改用登录或更换手机号",
    ),
    ErrorCode.ACCOUNT_DISABLED: (
        "该账号已被停用，请联系平台管理员。",
        "联系客服",
    ),
    ErrorCode.HOTEL_OFFLINE: (
        "该酒店已下架，暂不接受新预订。",
        "搜索同城其他酒店",
    ),
    ErrorCode.ROOM_TYPE_OFF_SALE: (
        "该房型已停售，暂不接受新预订。",
        "选择其他房型",
    ),
    ErrorCode.STOPPED_FOR_SALE: (
        "所选日期中有酒店停售的日期，无法预订。",
        "调整入住日期或选择其他房型",
    ),
    ErrorCode.NO_INVENTORY: (
        "所选日期中有日期已售完或剩余数量不足。",
        "减少间数、调整日期或选择其他房型",
    ),
    ErrorCode.INVENTORY_CONFLICT: (
        "刚才有其他顾客抢先订走了最后几间，库存已变化。",
        "刷新房型后重试",
    ),
    ErrorCode.PRICE_INVALID: (
        "价格必须是不小于 0 的数字。",
        "修改价格后重新保存",
    ),
    ErrorCode.STATE_NOT_ALLOWED: (
        "当前预订状态不允许执行该操作。",
        "刷新订单查看最新状态",
    ),
    ErrorCode.DUPLICATE_OPERATION: (
        "该操作已经执行过，系统不会重复处理。",
        "查看订单详情确认结果",
    ),
    ErrorCode.IDEMPOTENT_REPLAY: (
        "检测到重复提交，已返回第一次提交的结果。",
        "查看订单详情",
    ),
    ErrorCode.LOG_WRITE_FAILED: (
        "操作日志写入失败，业务操作已回滚，数据未发生变化。",
        "稍后重试",
    ),
    ErrorCode.INTERNAL_ERROR: (
        "系统内部出现异常，本次操作未生效。",
        "稍后重试或联系管理员",
    ),
}

_REASON_OVERRIDE: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_FAILED: "提交的内容不完整或不合法。",
    ErrorCode.INVALID_DATE_RANGE: "日期区间不合法。",
    ErrorCode.AUTH_REQUIRED: "尚未登录。",
    ErrorCode.INVALID_CREDENTIALS: "账号或密码错误。",
    ErrorCode.FORBIDDEN: "没有权限执行该操作。",
    ErrorCode.HOTEL_OFFLINE: "酒店当前不可预订。",
    ErrorCode.NO_INVENTORY: "库存不足。",
    ErrorCode.STATE_NOT_ALLOWED: "预订状态不允许该操作。",
}


class AppError(Exception):
    """A business failure that can be shown to the end user."""

    def __init__(
        self,
        code: ErrorCode,
        reason: str | None = None,
        advice: str | None = None,
        target: str | None = None,
    ) -> None:
        """Build an error with optional per-situation wording."""
        default_advice, default_target = _ADVICE[code]
        self.code = code
        self.reason = reason or _REASON_OVERRIDE.get(
            code, "操作未能完成。"
        )
        self.advice = advice or default_advice
        self.target = target or default_target
        super().__init__(f"{code.value} {self.reason}")

    def as_message(self) -> str:
        """Render the three-part hint used by the command line UI."""
        return (
            f"[{self.code.value}] {self.reason}\n"
            f"  建议：{self.advice}\n"
            f"  下一步：{self.target}"
        )

    def to_dict(self) -> dict[str, str]:
        """Return a serialisable form for logs and tests."""
        return {
            "code": self.code.value,
            "reason": self.reason,
            "advice": self.advice,
            "target": self.target,
        }
