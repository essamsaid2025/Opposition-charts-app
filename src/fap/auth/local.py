from __future__ import annotations

import hashlib
import os
import uuid

from fap.auth.base import Authenticator, auth_registry
from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.db.engine import Database
from fap.db.models import User

_ITERATIONS = 200_000


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS).hex()


@auth_registry.register
class LocalAuthenticator(Authenticator):
    """Username/password accounts stored in the app database (PBKDF2-SHA256)."""

    info = PluginInfo(id="local", name="Local Accounts", category="auth")

    def __init__(self, db: Database) -> None:
        self._db = db

    def authenticate(self, username: str, password: str) -> User | None:
        rows = self._db.query("SELECT * FROM users WHERE username = ?", (username,))
        if not rows:
            return None
        row = rows[0]
        if _hash(password, bytes.fromhex(row["salt"])) != row["password_hash"]:
            return None
        return User(id=row["id"], username=row["username"], role=row["role"])

    def create_user(self, username: str, password: str, role: str = "analyst") -> User:
        if self._db.query("SELECT 1 FROM users WHERE username = ?", (username,)):
            raise AuthError(f"User {username!r} already exists")
        salt = os.urandom(16)
        user = User(id=str(uuid.uuid4()), username=username, role=role)
        self._db.execute(
            "INSERT INTO users (id, username, password_hash, salt, role) VALUES (?, ?, ?, ?, ?)",
            (user.id, username, _hash(password, salt), salt.hex(), role),
        )
        return user
