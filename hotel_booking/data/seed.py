"""Demo data so that the program can be run without manual setup.

Two hotels in Nanjing, four room types and 60 days of stock; the
accounts cover the three roles and use passwords that satisfy the
policy (letters + digits).
"""

import datetime

from hotel_booking.data.database import Database
from hotel_booking.data.repositories import (
    HotelRepository,
    InventoryRepository,
    RoomTypeRepository,
    UserRepository,
)
from hotel_booking.domain import entities, enums
from hotel_booking.service.auth import hash_password

DEMO_PASSWORD = "Demo1234"
DAYS_OF_STOCK = 60


def seed_database(
    database: Database, today: datetime.date | None = None
) -> None:
    """Insert demo accounts, hotels, room types and stock once."""
    start = today or datetime.date.today()
    now = datetime.datetime.now()
    users = (
        entities.User(
            user_id="U1001",
            phone="13800000001",
            password_hash=hash_password(DEMO_PASSWORD),
            role=enums.Role.CUSTOMER,
            display_name="张洋",
        ),
        entities.User(
            user_id="U2001",
            phone="13900000001",
            password_hash=hash_password(DEMO_PASSWORD),
            role=enums.Role.STAFF,
            display_name="栖云酒店前台",
            hotel_id="H1001",
        ),
        entities.User(
            user_id="U2002",
            phone="13900000002",
            password_hash=hash_password(DEMO_PASSWORD),
            role=enums.Role.STAFF,
            display_name="江畔饭店前台",
            hotel_id="H1002",
        ),
        entities.User(
            user_id="U9001",
            phone="13700000001",
            password_hash=hash_password(DEMO_PASSWORD),
            role=enums.Role.ADMIN,
            display_name="平台管理员",
        ),
    )
    hotels = (
        entities.Hotel(
            hotel_id="H1001",
            name="栖云酒店",
            city="南京",
            address="中山路 88 号",
            star=4,
            status=enums.HotelStatus.ONLINE,
            staff_id="U2001",
        ),
        entities.Hotel(
            hotel_id="H1002",
            name="江畔饭店",
            city="南京",
            address="滨江大道 6 号",
            star=5,
            status=enums.HotelStatus.ONLINE,
            staff_id="U2002",
        ),
    )
    rooms = (
        entities.RoomType(
            "R1001", "H1001", "枕云·和风榻榻米", 2, "榻榻米", 42800
        ),
        entities.RoomType(
            "R1002", "H1001", "栖云·云栖双床房", 2, "双床", 51600
        ),
        entities.RoomType(
            "R2001", "H1002", "江景大床房", 2, "大床", 60200
        ),
        entities.RoomType(
            "R2002", "H1002", "标准单人房", 1, "单人床", 32800
        ),
    )
    with database.transaction() as conn:
        for user in users:
            if UserRepository.get_by_phone(conn, user.phone) is None:
                UserRepository.insert(conn, user, now)
        for hotel in hotels:
            if HotelRepository.get(conn, hotel.hotel_id) is None:
                HotelRepository.insert(conn, hotel)
        for room in rooms:
            if RoomTypeRepository.get(conn, room.room_type_id) is None:
                RoomTypeRepository.insert(conn, room)
        for room in rooms:
            for offset in range(DAYS_OF_STOCK):
                stay_date = start + datetime.timedelta(days=offset)
                price = _weekend_price(room.base_price_cents, stay_date)
                InventoryRepository.upsert(
                    conn,
                    entities.DailyInventory(
                        room_type_id=room.room_type_id,
                        stay_date=stay_date,
                        total_rooms=6,
                        available_rooms=6,
                        price_cents=price,
                    ),
                )


def _weekend_price(base_price_cents: int, stay_date: datetime.date) -> int:
    """Friday and Saturday nights cost 15 percent more."""
    if stay_date.weekday() in (4, 5):
        return int(base_price_cents * 1.15)
    return base_price_cents
