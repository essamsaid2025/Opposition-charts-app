from fap.auth.base import Authenticator, auth_registry
from fap.auth import local  # noqa: F401  (registers the built-in provider)
__all__ = ["Authenticator", "auth_registry"]
