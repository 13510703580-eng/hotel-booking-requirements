"""Account, password and permission tests (REQ-001, REQ-019)."""

import datetime

import pytest

from hotel_booking.domain import enums
from hotel_booking.domain.errors import AppError, ErrorCode


def test_demo_password_is_not_stored_in_plain_text(app):
    user = app.login("13800000001", "Demo1234").user
    assert user is not None
    assert "Demo1234" not in user.password_hash
    assert user.password_hash.startswith("pbkdf2_sha256$")


def test_login_with_wrong_password_is_rejected(app):
    with pytest.raises(AppError) as info:
        app.login("13800000001", "Wrong1234")
    assert info.value.code is ErrorCode.INVALID_CREDENTIALS
    assert "密码" in info.value.reason


def test_register_requires_digits_in_password(app):
    with pytest.raises(AppError) as info:
        app.register_customer("13600000001", "abcdefgh", "王五")
    assert info.value.code is ErrorCode.VALIDATION_FAILED
    assert "数字" in info.value.as_message()


def test_duplicate_phone_is_rejected(app):
    with pytest.raises(AppError) as info:
        app.register_customer("13800000001", "Demo12345", "重复")
    assert info.value.code is ErrorCode.ACCOUNT_EXISTS


def test_registered_customer_can_log_in(app):
    app.register_customer("13600000009", "Demo1234", "新顾客")
    session = app.login("13600000009", "Demo1234")
    assert session.role is enums.Role.CUSTOMER


def test_customer_cannot_use_staff_features(app, customer):
    with pytest.raises(AppError) as info:
        app.booking.list_hotel(customer)
    assert info.value.code is ErrorCode.FORBIDDEN


def test_staff_cannot_manage_another_hotel(app):
    staff = app.login("13900000001", "Demo1234")
    other = app.login("13900000002", "Demo1234")
    with pytest.raises(AppError) as info:
        app.inventory.set_daily_inventory(
            staff, "R2001", datetime.date.today(), 3, 60200
        )
    assert info.value.code is ErrorCode.FORBIDDEN
    assert "其他酒店" in info.value.reason
    assert other.user.hotel_id == "H1002"


def test_staff_account_created_by_admin_has_role(app, admin):
    user = app.auth.create_staff_account(
        admin, "13500000001", "Demo1234", "新前台", "H1001"
    )
    assert user.role is enums.Role.STAFF
    assert app.login("13500000001", "Demo1234").user.hotel_id == "H1001"


def test_customer_cannot_create_staff_account(app, customer):
    with pytest.raises(AppError) as info:
        app.auth.create_staff_account(
            customer, "13500000002", "Demo1234", "越权", "H1001"
        )
    assert info.value.code is ErrorCode.FORBIDDEN
