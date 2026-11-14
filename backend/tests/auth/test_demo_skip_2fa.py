"""DEMO_SKIP_2FA: invented demo staff skip 2FA setup on a developer's machine only. Company users
never have to set up the app (Decision #45)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.modules.auth.service import restrictions
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.platform.staff import service as staff_service
from app.platform.staff.models import PlatformStaff

OWNER = Role(key="owner", name="Owner", scope="all")


def _user(email: str) -> User:
    return User(email=email, name="X", must_change_password=False, totp_enabled=False)


def _staff(email: str) -> PlatformStaff:
    return PlatformStaff(email=email, name="X", must_change_password=False, totp_enabled=False)


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_skip_2fa", True)


def test_owner_never_has_to_set_up_the_app():
    assert restrictions(_user("riya@acme-academy.in"), OWNER) == []
    assert restrictions(_user("owner@acme.demo"), OWNER) == []


def test_demo_owner_and_demo_staff_skip_2fa_when_switched_on(demo_on):
    assert restrictions(_user("owner@acme.demo"), OWNER) == []
    assert staff_service.restrictions(_staff("staff@demo.versnq.in")) == []


def test_real_staff_still_need_2fa_when_switched_on(demo_on):
    assert staff_service.restrictions(_staff("suyog@versnq.in")) == ["two_factor_setup_required"]
    assert staff_service.restrictions(_staff("x@notdemo.versnq.in")) == [
        "two_factor_setup_required"
    ]


def test_switch_is_refused_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("DEMO_SKIP_2FA", "true")
    with pytest.raises(ValidationError, match="DEMO_SKIP_2FA"):
        Settings()
