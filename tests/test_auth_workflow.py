import pytest

from fap.auth.local import LocalAuthenticator
from fap.auth.workflow import (
    BOOTSTRAP_ADMIN_PASSWORD, BOOTSTRAP_ADMIN_USERNAME,
    ensure_bootstrap_admin, is_development,
)
from fap.config.settings import AppSettings
from fap.core.exceptions import AuthError
from fap.db.engine import Database


@pytest.fixture()
def auth(tmp_path) -> LocalAuthenticator:
    return LocalAuthenticator(Database(tmp_path / "auth.sqlite3"))


def test_environment_detection() -> None:
    assert is_development(AppSettings(environment="development"))
    assert is_development(AppSettings(environment=" Development "))
    assert not is_development(AppSettings(environment="production"))
    assert not is_development(AppSettings())  # default is production


def test_first_run_creates_admin_once(auth: LocalAuthenticator) -> None:
    assert not auth.has_any_users()
    assert ensure_bootstrap_admin(auth) is True
    user = auth.authenticate(BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_PASSWORD)
    assert user is not None and user.role == "admin"
    assert user.must_change_password is True
    # never recreated once users exist
    assert ensure_bootstrap_admin(auth) is False


def test_bootstrap_skipped_when_users_exist(auth: LocalAuthenticator) -> None:
    auth.create_user("maria", "supersecret1")
    assert ensure_bootstrap_admin(auth) is False
    assert auth.authenticate(BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_PASSWORD) is None


def test_forced_password_change_flow(auth: LocalAuthenticator) -> None:
    ensure_bootstrap_admin(auth)
    auth.change_password(BOOTSTRAP_ADMIN_USERNAME, "new-strong-pass")
    assert auth.authenticate(BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_PASSWORD) is None
    user = auth.authenticate(BOOTSTRAP_ADMIN_USERNAME, "new-strong-pass")
    assert user is not None and user.must_change_password is False


def test_password_policy_and_unknown_user(auth: LocalAuthenticator) -> None:
    ensure_bootstrap_admin(auth)
    with pytest.raises(AuthError):
        auth.change_password(BOOTSTRAP_ADMIN_USERNAME, "short")
    with pytest.raises(AuthError):
        auth.change_password("ghost", "long-enough-pass")


def test_migration_upgrades_existing_db(tmp_path) -> None:
    """A DB created before migration 2 gains the column transparently."""
    db_path = tmp_path / "old.sqlite3"
    db = Database(db_path)                     # applies all migrations
    LocalAuthenticator(db).create_user("legacy", "password123")
    db.close()
    db2 = Database(db_path)                    # reopen: idempotent migrations
    user = LocalAuthenticator(db2).authenticate("legacy", "password123")
    assert user is not None and user.must_change_password is False
