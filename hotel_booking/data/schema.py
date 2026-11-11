"""SQLite schema of the hotel booking system.

The schema is deliberately kept in one file so that the physical data
model can be compared with the class diagram of experiment two:

* ``users``        <- ``User`` / ``Customer`` / ``Staff`` / ``Admin``
* ``hotels``       <- ``Hotel``
* ``room_types``   <- ``RoomType``
* ``inventory``    <- ``DailyInventory`` (unique on room type + date)
* ``bookings``     <- ``Booking`` (unique on idempotency key)
* ``logs``         <- ``OperationLog``
"""

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id       TEXT PRIMARY KEY,
        phone         TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL,
        display_name  TEXT NOT NULL,
        hotel_id      TEXT,
        enabled       INTEGER NOT NULL DEFAULT 1,
        created_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hotels (
        hotel_id   TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        city       TEXT NOT NULL,
        address    TEXT NOT NULL,
        star       INTEGER NOT NULL,
        status     TEXT NOT NULL,
        staff_id   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS room_types (
        room_type_id     TEXT PRIMARY KEY,
        hotel_id         TEXT NOT NULL,
        name             TEXT NOT NULL,
        capacity         INTEGER NOT NULL,
        bed_type         TEXT NOT NULL,
        base_price_cents INTEGER NOT NULL,
        sale_status      TEXT NOT NULL,
        FOREIGN KEY (hotel_id) REFERENCES hotels (hotel_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory (
        room_type_id    TEXT NOT NULL,
        stay_date       TEXT NOT NULL,
        total_rooms     INTEGER NOT NULL,
        available_rooms INTEGER NOT NULL,
        price_cents     INTEGER NOT NULL,
        stopped         INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (room_type_id, stay_date),
        FOREIGN KEY (room_type_id)
            REFERENCES room_types (room_type_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bookings (
        booking_id       TEXT PRIMARY KEY,
        customer_id      TEXT NOT NULL,
        hotel_id         TEXT NOT NULL,
        room_type_id     TEXT NOT NULL,
        check_in         TEXT NOT NULL,
        check_out        TEXT NOT NULL,
        rooms            INTEGER NOT NULL,
        unit_price_cents INTEGER NOT NULL,
        total_cents      INTEGER NOT NULL,
        status           TEXT NOT NULL,
        idempotency_key  TEXT NOT NULL UNIQUE,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL,
        cancel_reason    TEXT NOT NULL DEFAULT '',
        operator_id      TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS logs (
        log_id        TEXT PRIMARY KEY,
        operator_id   TEXT NOT NULL,
        operator_role TEXT NOT NULL,
        object_type   TEXT NOT NULL,
        object_id     TEXT NOT NULL,
        action        TEXT NOT NULL,
        before_state  TEXT NOT NULL,
        after_state   TEXT NOT NULL,
        result        TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        detail        TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bookings_customer "
    "ON bookings (customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_bookings_hotel "
    "ON bookings (hotel_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_date "
    "ON inventory (stay_date)",
    "CREATE INDEX IF NOT EXISTS idx_logs_created "
    "ON logs (created_at)",
)

SCHEMA_VERSION = 1
