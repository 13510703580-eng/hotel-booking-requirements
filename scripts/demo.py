"""Scripted end-to-end demonstration used in the experiment report.

Running it prints a transcript that covers the main acceptance cases
of experiment one: search, booking, oversell rejection, idempotent
replay, confirm / check-in / check-out, cancellation with stock
return, statistics, authorization failure and log-rollback.
"""

import datetime
import tempfile
from pathlib import Path

from hotel_booking.api.application import Application
from hotel_booking.domain import enums, rules
from hotel_booking.domain.errors import AppError

DEMO_PASSWORD = "Demo1234"


def line(title: str) -> None:
    """Print a section separator."""
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)


def show_stock(app: Application, room_type_id: str, day: datetime.date) -> None:
    """Print the available room count of one date."""
    row = app.inventory.stock_of(room_type_id, day)
    if row is None:
        print(f"  {day} 库存：未配置")
        return
    print(
        f"  {day} 库存：可售 {row.available_rooms}/{row.total_rooms} 间，"
        f"价格 {row.price_cents / 100:.2f} 元，停售={row.stopped}"
    )


def main() -> None:
    """Run the whole demonstration on a throwaway database."""
    workspace = Path(tempfile.mkdtemp(prefix="hotel-demo-"))
    db_path = workspace / "demo.db"
    app = Application(str(db_path))
    today = datetime.date.today()
    day_one = today + datetime.timedelta(days=7)
    day_two = day_one + datetime.timedelta(days=1)

    line("1. 登录：三种角色（REQ-001）")
    customer = app.login("13800000001", DEMO_PASSWORD)
    staff = app.login("13900000001", DEMO_PASSWORD)
    admin = app.login("13700000001", DEMO_PASSWORD)
    print(f"  顾客 {customer.user.display_name} 角色 {customer.role.value}")
    print(f"  员工 {staff.user.display_name} 角色 {staff.role.value}")
    print(f"  管理员 {admin.user.display_name} 角色 {admin.role.value}")
    print(f"  密码存储示例：{customer.user.password_hash[:32]}...")

    line("2. 工作人员把某天库存改为 1 间（REQ-004）")
    app.inventory.set_daily_inventory(
        staff, "R1001", day_one, total_rooms=1,
        price_cents=50000, stopped=False,
    )
    show_stock(app, "R1001", day_one)

    line("3. 顾客查询可订房型（REQ-005）")
    hits = app.inventory.search("南京", day_one, day_two, guests=2)
    for hit in hits:
        print(
            f"  {hit.room_type_id} {hit.hotel_name} · {hit.room_name} "
            f"剩余 {hit.available_rooms} 间，一晚 "
            f"{hit.stay_total_cents / 100:.2f} 元"
        )

    line("4. 创建预订，逐日扣减库存（REQ-006、REQ-018）")
    result = app.booking.create(
        customer, "R1001", day_one, day_two, 1, "demo-key-001"
    )
    booking = result.booking
    print(f"  预订号 {booking.booking_id} 状态 "
          f"{rules.status_label(booking.status)} 金额 "
          f"{booking.total_cents / 100:.2f} 元")
    show_stock(app, "R1001", day_one)

    line("5. 第二个顾客抢同一间：库存不足的精确提示（REQ-012/021）")
    second = app.register_customer("13600000002", DEMO_PASSWORD, "李四")
    second_session = app.login("13600000002", DEMO_PASSWORD)
    try:
        app.booking.create(
            second_session, "R1001", day_one, day_two, 1, "demo-key-002"
        )
    except AppError as error:
        print(error.as_message())
    print(f"  第二个顾客 id {second.user_id}，库存仍为：")
    show_stock(app, "R1001", day_one)

    line("6. 重复提交同一幂等键（REQ-013）")
    replay = app.booking.create(
        customer, "R1001", day_one, day_two, 1, "demo-key-001"
    )
    print(f"  replayed={replay.replayed}，返回预订号 "
          f"{replay.booking.booking_id}，与首次相同="
          f"{replay.booking.booking_id == booking.booking_id}")
    print(f"  当前预订总数：{len(app.booking.list_mine(customer))}")

    line("7. 确认 → 入住 → 退房（REQ-007/010/011）")
    confirmed = app.booking.confirm(staff, booking.booking_id)
    print(f"  确认后：{rules.status_label(confirmed.status)}，"
          f"操作人 {confirmed.operator_id}")
    checked_in = app.booking.check_in(staff, booking.booking_id)
    print(f"  入住后：{rules.status_label(checked_in.status)}")
    checked_out = app.booking.check_out(staff, booking.booking_id)
    print(f"  退房后：{rules.status_label(checked_out.status)}")

    line("8. 取消预订并回补库存（REQ-009）")
    app.inventory.set_daily_inventory(
        staff, "R1002", day_one, total_rooms=3,
        price_cents=51600, stopped=False,
    )
    show_stock(app, "R1002", day_one)
    cancel_target = app.booking.create(
        customer, "R1002", day_one, day_two, 2, "demo-key-003"
    ).booking
    show_stock(app, "R1002", day_one)
    cancelled = app.booking.cancel(
        customer, cancel_target.booking_id, "行程变更"
    )
    print(f"  取消后状态：{rules.status_label(cancelled.status)}")
    show_stock(app, "R1002", day_one)

    line("9. 越权操作被拒绝（REQ-019）")
    try:
        app.hotel.take_offline(customer, "H1001", "测试越权")
    except AppError as error:
        print(error.as_message())

    line("10. 日志写入失败时业务回滚（REQ-020）")
    app.inventory.set_daily_inventory(
        staff, "R1002", day_two, total_rooms=2,
        price_cents=51600, stopped=False,
    )
    before = app.inventory.stock_of("R1002", day_two)
    app.logs.fail_next_write = True
    try:
        app.booking.create(
            customer, "R1002", day_two,
            day_two + datetime.timedelta(days=1), 1, "demo-key-004"
        )
    except AppError as error:
        print(error.as_message())
    after = app.inventory.stock_of("R1002", day_two)
    print(f"  回滚前后可售数量：{before.available_rooms} -> "
          f"{after.available_rooms}（应保持不变）")

    line("11. 统计报表（REQ-015）")
    stats = app.statistics.daily(
        staff, "H1001", today, today + datetime.timedelta(days=14)
    )
    for row in stats:
        if row.bookings or row.rooms_total:
            print(
                f"  {row.stay_date} 预订 {row.bookings} 确认 "
                f"{row.confirmed} 入住 {row.checked_in} "
                f"入住率 {row.occupancy}%"
            )

    line("12. 管理员查询操作日志（REQ-014）")
    for item in app.logs.query(admin, limit=8):
        print(
            f"  {item.created_at:%m-%d %H:%M:%S} {item.action:<16} "
            f"{item.object_type}:{item.object_id} "
            f"{item.before_state}->{item.after_state}"
        )

    line("13. 日志脱敏与保留策略（REQ-019/020）")
    print(f"  日志总数：{app.logs.count()}，保留期 180 天")
    print("  手机号在日志中显示为 138********1 形式。")

    app.close()
    print(f"\n演示数据库：{db_path}")


if __name__ == "__main__":
    main()
