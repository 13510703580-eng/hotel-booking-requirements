"""Application facade wiring all services together.

A command line client (or a future web controller) talks to this
object only; it never touches repositories directly.  Keeping one
assembly point makes the dependency graph explicit:

    Application
      -> AuthService, LogService
      -> HotelService, InventoryService, BookingService, StatisticsService
"""

from hotel_booking.data.database import Database
from hotel_booking.data.seed import seed_database
from hotel_booking.domain import entities
from hotel_booking.domain.errors import AppError
from hotel_booking.service.auth import AuthService, Session
from hotel_booking.service.booking import BookingService
from hotel_booking.service.hotel import HotelService
from hotel_booking.service.inventory import InventoryService
from hotel_booking.service.log import LogService
from hotel_booking.service.statistics import StatisticsService


class Application:
    """Assemble the object graph and expose high level use cases."""

    def __init__(
        self, db_path: str = "hotel_booking.db", with_seed: bool = True
    ) -> None:
        """Create the database, services and optional demo data."""
        self.database = Database(db_path)
        self.logs = LogService(self.database)
        self.auth = AuthService(self.database)
        self.hotel = HotelService(self.database, self.logs)
        self.inventory = InventoryService(self.database, self.logs)
        self.booking = BookingService(self.database, self.logs)
        self.statistics = StatisticsService(self.database)
        if with_seed:
            seed_database(self.database)

    def register_customer(
        self, phone: str, password: str, display_name: str
    ) -> entities.User:
        """Register a customer account."""
        return self.auth.register_customer(phone, password, display_name)

    def login(self, phone: str, password: str) -> Session:
        """Log in and return a session."""
        return self.auth.login(phone, password)

    def close(self) -> None:
        """Release database resources."""
        self.database.close()

    def __enter__(self) -> "Application":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def describe_error(error: AppError) -> str:
    """Render an :class:`AppError` as the three-line user hint."""
    return error.as_message()
