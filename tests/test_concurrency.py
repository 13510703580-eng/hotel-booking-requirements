"""Oversell protection under real threads (REQ-018).

Twenty threads are released at the same moment against one remaining
room.  The conditional ``UPDATE ... WHERE available_rooms >= ?`` plus
``BEGIN IMMEDIATE`` must let exactly one of them win, and the stock
must never go negative.
"""

import datetime
import threading

from hotel_booking.api.application import Application
from hotel_booking.domain import enums
from hotel_booking.domain.errors import AppError

THREADS = 20


def test_only_one_of_twenty_bookings_wins(app, staff, today, tmp_path):
    day = today + datetime.timedelta(days=1)
    night = day + datetime.timedelta(days=1)
    app.inventory.set_daily_inventory(staff, "R1001", day, 1, 42800)
    db_path = str(tmp_path / "test.db")

    barrier = threading.Barrier(THREADS)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        local = Application(db_path, with_seed=False)
        try:
            session = local.login("13800000001", "Demo1234")
            barrier.wait(timeout=10)
            result = local.booking.create(
                session, "R1001", day, night, 1, f"race-{index}"
            )
            with lock:
                outcomes.append(result.booking.booking_id)
        except AppError:
            with lock:
                outcomes.append("")
        finally:
            local.close()

    threads = [
        threading.Thread(target=worker, args=(index,))
        for index in range(THREADS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    winners = [item for item in outcomes if item]
    assert len(outcomes) == THREADS
    assert len(winners) == 1
    stock = app.inventory.stock_of("R1001", day)
    assert stock.available_rooms == 0
    assert stock.available_rooms >= 0
    sold = app.booking.list_hotel(
        staff, (enums.BookingStatus.PENDING_CONFIRM,)
    )
    assert len(sold) == 1
