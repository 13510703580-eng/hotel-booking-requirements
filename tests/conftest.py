"""Shared fixtures for the test suite."""

import datetime

import pytest

from hotel_booking.api.application import Application


@pytest.fixture()
def app(tmp_path):
    """An isolated application with a file database and demo data."""
    database = Application(str(tmp_path / "test.db"))
    yield database
    database.close()


@pytest.fixture()
def today():
    """Today's date, so tests never hard-code a day."""
    return datetime.date.today()


@pytest.fixture()
def customer(app):
    """A logged-in customer session."""
    return app.login("13800000001", "Demo1234")


@pytest.fixture()
def staff(app):
    """A logged-in staff session of hotel H1001."""
    return app.login("13900000001", "Demo1234")


@pytest.fixture()
def admin(app):
    """A logged-in platform administrator session."""
    return app.login("13700000001", "Demo1234")
