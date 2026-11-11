"""Interactive command line client.

The menu is intentionally plain text: experiment three allows a GUI
but does not require one, so a console client keeps the focus on the
business rules.  All errors are rendered with the three-part hint of
REQ-021.
"""

import datetime
import sys

from hotel_booking.api.application import Application
from hotel_booking.domain import rules
from hotel_booking.domain.errors import AppError
from hotel_booking.service.auth import Session

MENU = """
=========== 栖云酒店预订系统 ===========
 1. 顾客登录          2. 工作人员登录
 3. 管理员登录        4. 注册顾客账号
 0. 退出
======================================"""


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "0"


def _ask_date_safe(prompt: str) -> datetime.date:
    raw = _ask(f"{prompt}（YYYY-MM-DD）：")
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        print("  日期格式应为 2026-11-07。")
        return datetime.date.today()


def _ask_int(prompt: str, default: int = 0) -> int:
    raw = _ask(f"{prompt}（默认 {default}）：")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print("  请输入整数。")
        return default


def main(db_path: str = "hotel_booking.db") -> int:
    """Run the interactive menu until the user chooses to exit."""
    app = Application(db_path)
    print("演示账号：顾客 13800000001 / 员工 13900000001 / 管理员 13700000001")
    print("统一密码：Demo1234")
    try:
        while True:
            print(MENU)
            choice = _ask("请选择：")
            if choice == "0":
                return 0
            try:
                if choice == "1":
                    _customer_flow(app, app.login(
                        _ask("手机号："), _ask("密码：")
                    ))
                elif choice == "2":
                    _staff_flow(app, app.login(
                        _ask("手机号："), _ask("密码：")
                    ))
                elif choice == "3":
                    _admin_flow(app, app.login(
                        _ask("手机号："), _ask("密码：")
                    ))
                elif choice == "4":
                    user = app.register_customer(
                        _ask("手机号："),
                        _ask("密码："),
                        _ask("昵称："),
                    )
                    print(f"  注册成功：{user.display_name} "
                          f"{user.masked_phone()}")
                else:
                    print("  没有这个选项。")
            except AppError as error:
                print(error.as_message())
    finally:
        app.close()


def _customer_flow(app: Application, session: Session) -> None:
    print(f"\n欢迎，{session.user.display_name}")
    while True:
        print("\n[顾客] 1 查询房型 2 创建预订 3 我的预订 4 取消预订 0 返回")
        choice = _ask("请选择：")
        if choice == "0":
            return
        try:
            if choice == "1":
                _search(app)
            elif choice == "2":
                _create(app, session)
            elif choice == "3":
                _list_mine(app, session)
            elif choice == "4":
                booking = app.booking.cancel(
                    session, _ask("预订编号："), _ask("取消原因：")
                )
                print(f"  已取消：{booking.booking_id} "
                      f"{rules.status_label(booking.status)}")
        except AppError as error:
            print(error.as_message())


def _search(app: Application) -> None:
    check_in = _ask_date_safe("入住日期")
    check_out = _ask_date_safe("离店日期")
    hits = app.inventory.search(
        city=_ask("城市：") or "南京",
        check_in=check_in,
        check_out=check_out,
        guests=_ask_int("入住人数", 1),
        keyword=_ask("房型关键字（可空）："),
    )
    if not hits:
        print("  没有符合条件的可订房型，请调整日期或城市。")
        return
    nights = (check_out - check_in).days
    for hit in hits:
        print(
            f"  {hit.room_type_id} {hit.hotel_name}({hit.star}星) "
            f"{hit.room_name} 可住{hit.capacity}人 剩余{hit.available_rooms}间 "
            f"总额 {hit.stay_total_cents / 100:.2f} 元/{nights}晚"
        )


def _create(app: Application, session: Session) -> None:
    room_type_id = _ask("房型编号：")
    check_in = _ask_date_safe("入住日期")
    check_out = _ask_date_safe("离店日期")
    rooms = _ask_int("间数", 1)
    key = _ask("幂等键（同一页面重复提交请用同一个）：")
    result = app.booking.create(
        session, room_type_id, check_in, check_out, rooms,
        key or f"key-{datetime.datetime.now().timestamp()}",
    )
    booking = result.booking
    prefix = "重复提交，返回原结果：" if result.replayed else "预订成功："
    print(
        f"  {prefix}{booking.booking_id} "
        f"{rules.status_label(booking.status)} "
        f"金额 {booking.total_cents / 100:.2f} 元"
    )


def _list_mine(app: Application, session: Session) -> None:
    bookings = app.booking.list_mine(session)
    if not bookings:
        print("  还没有预订记录。")
    for booking in bookings:
        print(
            f"  {booking.booking_id} {booking.check_in}~{booking.check_out} "
            f"{booking.rooms}间 {booking.total_cents / 100:.2f}元 "
            f"{rules.status_label(booking.status)}"
        )


def _staff_flow(app: Application, session: Session) -> None:
    print(f"\n工作台：{session.user.display_name}")
    while True:
        print(
            "\n[工作人员] 1 本酒店预订 2 确认 3 拒绝 4 入住 5 退房 "
            "6 设置库存 7 停业处理 8 统计 0 返回"
        )
        choice = _ask("请选择：")
        if choice == "0":
            return
        try:
            if choice == "1":
                for booking in app.booking.list_hotel(session):
                    print(
                        f"  {booking.booking_id} {booking.check_in}~"
                        f"{booking.check_out} {booking.rooms}间 "
                        f"{rules.status_label(booking.status)}"
                    )
            elif choice == "2":
                booking = app.booking.confirm(session, _ask("预订编号："))
                print(f"  已确认：{booking.booking_id}")
            elif choice == "3":
                booking = app.booking.reject(
                    session, _ask("预订编号："), _ask("拒绝原因：")
                )
                print(f"  已拒绝：{booking.booking_id}")
            elif choice == "4":
                booking = app.booking.check_in(session, _ask("预订编号："))
                print(f"  已入住：{booking.booking_id}")
            elif choice == "5":
                booking = app.booking.check_out(session, _ask("预订编号："))
                print(f"  已退房：{booking.booking_id}")
            elif choice == "6":
                _set_inventory(app, session)
            elif choice == "7":
                result = app.hotel.handle_closure(
                    session,
                    _ask("房型编号："),
                    _ask_date_safe("停业开始"),
                    _ask_date_safe("停业结束"),
                    _ask("停业原因："),
                )
                print(f"  已停业，联动取消预订 {result['cancelled']} 条。")
            elif choice == "8":
                _statistics(app, session)
        except AppError as error:
            print(error.as_message())


def _set_inventory(app: Application, session: Session) -> None:
    room_type_id = _ask("房型编号：")
    total = _ask_int("每日可售数量", 6)
    price_yuan = _ask_int("每日价格（元）", 428)
    result = app.inventory.bulk_set(
        session,
        room_type_id,
        _ask_date_safe("开始日期"),
        _ask_date_safe("结束日期"),
        total,
        price_yuan * 100,
    )
    print(f"  已更新 {result} 天库存。")


def _statistics(app: Application, session: Session) -> None:
    hotel_id = session.user.hotel_id or _ask("酒店编号：")
    rows = app.statistics.daily(
        session,
        hotel_id,
        _ask_date_safe("统计开始"),
        _ask_date_safe("统计结束"),
    )
    print("  统计口径：取消/拒绝不计入；跨日预订按入住日期逐日统计。")
    for row in rows:
        print(
            f"  {row.stay_date} 预订{row.bookings} 确认{row.confirmed} "
            f"入住{row.checked_in} 入住率{row.occupancy}%"
        )


def _admin_flow(app: Application, session: Session) -> None:
    print(f"\n平台后台：{session.user.display_name}")
    while True:
        print(
            "\n[管理员] 1 下架酒店 2 警告酒店 3 查询日志 4 创建员工账号 0 返回"
        )
        choice = _ask("请选择：")
        if choice == "0":
            return
        try:
            if choice == "1":
                result = app.hotel.take_offline(
                    session, _ask("酒店编号："), _ask("下架原因：")
                )
                print(
                    f"  已下架，联动取消 {result['cancelled']} 条预订，"
                    f"回补 {result['released_days']} 个房日。"
                )
            elif choice == "2":
                hotel = app.hotel.warn(
                    session, _ask("酒店编号："), _ask("警告原因：")
                )
                print(f"  已警告：{hotel.name}")
            elif choice == "3":
                logs = app.logs.query(session, limit=20)
                for item in logs:
                    print(
                        f"  {item.created_at:%m-%d %H:%M} {item.action} "
                        f"{item.object_type}:{item.object_id} "
                        f"{item.before_state}->{item.after_state} "
                        f"{item.masked_detail()}"
                    )
            elif choice == "4":
                user = app.auth.create_staff_account(
                    session,
                    _ask("手机号："),
                    _ask("密码："),
                    _ask("姓名："),
                    _ask("所属酒店编号："),
                )
                print(f"  已创建员工账号：{user.display_name}")
        except AppError as error:
            print(error.as_message())


if __name__ == "__main__":
    sys.exit(main())
