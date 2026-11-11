# 酒店预订系统（实验三）

《软件设计与体系结构》实验三的实现仓库。代码按实验二的 UML 包图分层实现，
使用 Python 3.12 + 标准库 `sqlite3`，无第三方运行时依赖，命令行界面。

## 1. 快速开始

```bash
python3 scripts/demo.py          # 脚本化演示全部验收场景
python3 -m hotel_booking.cli.app # 交互式命令行
python3 -m pytest tests -q       # 运行单元测试
python3 -m pylint hotel_booking --rcfile=pylintrc   # 代码风格检查
```

演示账号（密码统一为 `Demo1234`）：

| 角色 | 手机号 | 说明 |
| --- | --- | --- |
| 顾客 | 13800000001 | 张洋 |
| 工作人员 | 13900000001 | 栖云酒店（H1001） |
| 工作人员 | 13900000002 | 江畔饭店（H1002） |
| 管理员 | 13700000001 | 平台管理员 |

首次运行时 `hotel_booking/data/seed.py` 会写入两家南京酒店、四个房型、
60 天库存（每房型每日 6 间，周五周六价格 ×1.15）。

## 2. 目录结构

```
hotel_booking/
  domain/      纯业务规则：枚举、实体、状态机、日期与金额校验、错误
  data/        SQLite 访问：表结构、连接与事务、仓储、种子数据
  service/     用例编排与事务边界：认证、日志、库存、预订、酒店、统计
  api/         装配层：Application 统一组装服务并对外暴露用例
  cli/         命令行界面
scripts/demo.py 报告用的脚本化演示
tests/         68 个单元测试（含 20 线程并发抢房）
```

依赖方向严格单向：`cli → api → service → data → domain`，
`domain` 不依赖任何其他层，因此规则可以脱离数据库直接测试。

## 3. 需求到代码的映射

| 需求 | 实现位置 |
| --- | --- |
| REQ-001 三角色与数据范围 | `service/auth.py::AuthService`、`require_hotel_scope` |
| REQ-002 酒店维护与审核下架 | `service/hotel.py::update_info/warn/take_offline` |
| REQ-003 房型与价格快照 | `service/hotel.py::update_room_type`、`Booking.unit_price_cents` |
| REQ-004 每日库存与停售 | `service/inventory.py`、`InventoryRepository.upsert` |
| REQ-005 多条件查询 | `data/repositories.py::SearchRepository` |
| REQ-006 逐日扣减 | `service/booking.py::create`、`InventoryRepository.try_reserve` |
| REQ-007 确认与重复确认 | `service/booking.py::confirm` |
| REQ-008 修改预订 | `service/booking.py::modify`、`BookingRepository.update_stay` |
| REQ-009 取消与库存回补 | `service/booking.py::cancel` |
| REQ-010 / 011 入住与退房 | `service/booking.py::check_in/check_out` |
| REQ-012 无房与停业 | `domain/rules.py::describe_shortage`、`HotelService.handle_closure` |
| REQ-013 重复提交与旧页面 | `bookings.idempotency_key` 唯一索引、所有状态更新带旧状态条件 |
| REQ-014 日志记录与查询 | `service/log.py`、`LogService.write(conn, ...)` 与业务同事务 |
| REQ-015 统计口径 | `service/statistics.py`（模块文档写明口径） |
| REQ-016 违规处理与下架 | `HotelService.take_offline` 联动取消并回补库存 |
| REQ-017 性能 | 全部查询走索引，20 并发在测试中验证 |
| REQ-018 并发不超卖 | `BEGIN IMMEDIATE` + `available_rooms >= ?` 条件更新 |
| REQ-019 安全 | PBKDF2-HMAC-SHA256、越权检查、日志手机号脱敏 |
| REQ-020 日志保留与一致性 | 同事务写入、`purge_expired(180)` |
| REQ-021 可行动的错误提示 | `domain/errors.py::AppError.as_message()` 三段式 |

## 4. 关键设计说明

**并发不超卖。** 扣库存不是"先读后写"，而是一条带谓词的条件更新：

```sql
UPDATE inventory SET available_rooms = available_rooms - ?
WHERE room_type_id = ? AND stay_date = ? AND available_rooms >= ?
```

`rowcount` 为 0 即表示抢房失败，失败请求不会留下任何预订行。
外层再用 `BEGIN IMMEDIATE` 提前拿写锁，避免两个事务同时读到旧值。

**业务与日志同生共死。** `LogService.write` 接收调用方事务的连接，
预订行、库存行、日志行在同一次 `COMMIT` 中落盘；`tests/test_transaction.py`
通过 `fail_next_write` 注入故障，验证日志失败时库存与预订均回滚。

**旧页面不覆盖新状态。** 所有状态变更都是
`WHERE booking_id = ? AND status = <进入该操作时看到的状态>`，
更新失败即抛 `STATE_NOT_ALLOWED`；重复确认、重复入住、重复取消都走
"目标状态已是当前状态就返回原结果"的短路，库存只回补一次。

## 5. 代码规模与风格

- 产品代码 22 个文件、物理行 3704 行，其中有效代码行 3052 行（不含空行、
  注释与文档字符串），超过实验要求的 1500 行。
- `python3 -m pylint hotel_booking --rcfile=pylintrc` 评分 10.00/10。
  `pylintrc` 只放宽了实体/仓储这类天然多字段的阈值，关闭 `duplicate-code`
  （审计日志的固定字段模板在各服务中重复书写，属于刻意保持的可读性）。
- 单元测试 68 个，全部通过，覆盖并发、幂等、状态机、权限、统计口径、
  日志回滚与脱敏。
