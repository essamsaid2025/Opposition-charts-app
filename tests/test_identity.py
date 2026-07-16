"""Identity & authorization layer (Phase 3A).

Everything below the Streamlit facade is pure, so the whole who-gets-in-as-what
decision is tested here from raw OIDC claims - no browser, no network.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from fap.identity.config import load_identity_config
from fap.identity.models import Identity
from fap.identity.policy import AccessPolicy
from fap.identity.provider import identity_registry, load_builtin_identity_providers
from fap.identity.roles import DEFAULT_ROLE, Role, all_roles, role_from_slug
from fap.identity.service import IdentityService

load_builtin_identity_providers()


# ---------------------------------------------------------------- roles
def test_twelve_roles_defined_and_ranked():
    roles = all_roles()
    assert len(roles) == 12
    assert roles[0] is Role.SUPER_ADMIN and roles[-1] is Role.READ_ONLY
    ranks = [r.rank for r in roles]
    assert ranks == sorted(ranks, reverse=True)      # strictly ordered by authority


def test_role_comparison_by_authority():
    assert Role.SUPER_ADMIN >= Role.CLUB_ADMIN > Role.HEAD_COACH
    assert Role.READ_ONLY < Role.SCOUT
    assert not (Role.READ_ONLY >= Role.HEAD_COACH)


def test_role_from_slug_is_fail_closed():
    assert role_from_slug("head_coach") is Role.HEAD_COACH
    assert role_from_slug("HEAD_COACH") is Role.HEAD_COACH
    assert role_from_slug("nonsense") is None          # unknown -> no default -> rejected
    assert role_from_slug(None, DEFAULT_ROLE) is DEFAULT_ROLE


# ---------------------------------------------------------------- providers
def test_all_required_providers_registered():
    assert {"microsoft", "google", "okta", "auth0", "keycloak", "dev"} <= set(identity_registry.ids())


def test_entra_claim_normalization():
    entra = identity_registry.create("microsoft")
    identity = entra.normalize({"oid": "abc", "preferred_username": "Jo@Club.com",
                                "name": "Jo", "roles": ["First Team Analysts"]})
    assert identity.subject == "abc"
    assert identity.email == "jo@club.com"             # lowercased
    assert identity.name == "Jo" and identity.domain == "club.com"
    assert identity.groups == ("First Team Analysts",)
    assert identity.provider_id == "microsoft"


def test_google_and_okta_use_their_own_claim_shapes():
    g = identity_registry.create("google").normalize({"sub": "g1", "email": "a@club.com"})
    assert g.subject == "g1" and g.provider_id == "google"
    o = identity_registry.create("okta").normalize(
        {"sub": "o1", "preferred_username": "b@club.com", "groups": "Coaches,Staff"})
    assert o.email == "b@club.com" and o.groups == ("Coaches", "Staff")


def test_pages_never_import_streamlit_from_the_pure_layer():
    import fap.identity.policy, fap.identity.service, fap.identity.roles
    for mod in (fap.identity.policy, fap.identity.service, fap.identity.roles):
        assert "streamlit" not in getattr(mod, "__dict__", {})


# ---------------------------------------------------------------- policy
def _identity(email, groups=(), provider="microsoft"):
    return Identity(subject=email, email=email, name=email, provider_id=provider, groups=tuple(groups))


def test_allowed_domain_gets_default_role():
    policy = AccessPolicy(allowed_domains=frozenset({"club.com"}), default_role=Role.READ_ONLY)
    d = policy.resolve(_identity("jo@club.com"))
    assert d.allowed and d.role is Role.READ_ONLY


def test_role_assignment_beats_default_and_groups():
    policy = AccessPolicy(allowed_domains=frozenset({"club.com"}),
                          role_assignments={"boss@club.com": "club_admin"},
                          group_roles={"analysts": "first_team_analyst"},
                          default_role=Role.READ_ONLY)
    d = policy.resolve(_identity("boss@club.com", groups=["Analysts"]))
    assert d.role is Role.CLUB_ADMIN


def test_group_role_used_when_no_email_assignment():
    policy = AccessPolicy(allowed_domains=frozenset({"club.com"}),
                          group_roles={"first team analysts": "first_team_analyst"},
                          default_role=Role.READ_ONLY)
    d = policy.resolve(_identity("an@club.com", groups=["First Team Analysts"]))
    assert d.role is Role.FIRST_TEAM_ANALYST


def test_highest_group_role_wins():
    policy = AccessPolicy(allowed_domains=frozenset({"club.com"}),
                          group_roles={"scouts": "scout", "coaches": "head_coach"})
    d = policy.resolve(_identity("x@club.com", groups=["Scouts", "Coaches"]))
    assert d.role is Role.HEAD_COACH


def test_email_whitelist_admits_any_domain():
    policy = AccessPolicy(email_whitelist=frozenset({"consultant@gmail.com"}),
                          default_role=Role.SCOUT)
    assert policy.resolve(_identity("consultant@gmail.com")).allowed
    assert not policy.resolve(_identity("stranger@gmail.com")).allowed


def test_outside_domain_denied_and_yields_no_user():
    policy = AccessPolicy(allowed_domains=frozenset({"club.com"}))
    d = policy.resolve(_identity("x@other.com"))
    assert not d.allowed and d.role is None
    with pytest.raises(ValueError):
        d.user(_identity("x@other.com"))


def test_empty_policy_fails_closed():
    policy = AccessPolicy()                              # nothing configured
    assert policy.admits_no_one
    assert not policy.resolve(_identity("anyone@club.com")).allowed


def test_fail_open_only_when_explicitly_disabled():
    policy = AccessPolicy(allowed_domains=frozenset({"club.com"}), fail_closed=False)
    # even fail_open still requires the domain rule to match
    assert policy.resolve(_identity("a@club.com")).allowed
    assert not policy.resolve(_identity("a@other.com")).allowed


# ---------------------------------------------------------------- service + config
SECRETS = {
    "auth": {"microsoft": {"client_id": "x",
             "server_metadata_url": "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration"}},
    "identity": {
        "providers": ["microsoft"],
        "allowed_domains": ["club.com"],
        "default_role": "read_only",
        "role_assignments": {"boss@club.com": "club_admin"},
        "group_roles": {"First Team Analysts": "first_team_analyst"},
        "organization": "Example FC",
        "session_timeout_minutes": 120,
        "remember_session": True,
    },
}


def test_config_parses_policy_and_session():
    cfg = load_identity_config(SECRETS)
    assert cfg.providers == ("microsoft",)
    assert cfg.configured and not cfg.development
    assert cfg.session_timeout_minutes == 120 and cfg.remember_session is True
    assert cfg.policy.organization == "Example FC"


def test_config_infers_providers_from_auth_sections_when_unspecified():
    secrets = {"auth": {"google": {"client_id": "g"}}, "identity": {"allowed_domains": ["c.com"]}}
    assert load_identity_config(secrets).providers == ("google",)


def test_dev_provider_added_only_in_development():
    assert "dev" not in load_identity_config(SECRETS).providers
    assert "dev" in load_identity_config(SECRETS, development=True).providers


# ---------------------------------------------------------------- development mode
def test_development_mode_triggered_by_auth_provider_env(monkeypatch):
    from fap.identity.config import development_mode
    monkeypatch.delenv("FAP_ENVIRONMENT", raising=False)
    monkeypatch.setenv("FAP_AUTH_PROVIDER", "dev")
    assert development_mode() is True


def test_development_mode_triggered_by_environment_env(monkeypatch):
    from fap.identity.config import development_mode
    monkeypatch.delenv("FAP_AUTH_PROVIDER", raising=False)
    monkeypatch.setenv("FAP_ENVIRONMENT", "development")
    assert development_mode() is True


def test_production_is_not_development_by_default(monkeypatch):
    from fap.identity.config import development_mode
    monkeypatch.delenv("FAP_AUTH_PROVIDER", raising=False)
    monkeypatch.delenv("FAP_ENVIRONMENT", raising=False)
    assert development_mode() is False          # default settings environment = production


def test_auth_provider_other_than_dev_stays_production(monkeypatch):
    from fap.identity.config import development_mode
    monkeypatch.delenv("FAP_ENVIRONMENT", raising=False)
    monkeypatch.setenv("FAP_AUTH_PROVIDER", "microsoft")
    assert development_mode() is False


def test_development_bypass_yields_super_admin_without_any_idp(monkeypatch):
    """The whole point: no Microsoft, no OAuth, no secrets.toml required."""
    import app
    monkeypatch.setenv("FAP_AUTH_PROVIDER", "dev")
    user = app.require_login()                  # must NOT stop or need a provider
    assert user.role is Role.SUPER_ADMIN and user.email == "developer@localhost"


def test_service_resolves_claims_to_authorized_user():
    svc = IdentityService(load_identity_config(SECRETS))
    decision, user = svc.resolve("microsoft", {"oid": "1", "email": "boss@club.com", "name": "Boss"})
    assert decision.allowed and user.role is Role.CLUB_ADMIN
    assert user.organization == "Example FC" and user.email == "boss@club.com"


def test_service_denies_outsider_with_no_user():
    svc = IdentityService(load_identity_config(SECRETS))
    decision, user = svc.resolve("microsoft", {"oid": "2", "email": "x@rival.com"})
    assert not decision.allowed and user is None


def test_offered_providers_follow_config_order():
    svc = IdentityService(load_identity_config(
        {"identity": {"providers": ["okta", "microsoft"], "allowed_domains": ["c.com"]}}))
    assert [p.info.id for p in svc.offered_providers()] == ["okta", "microsoft"]


# ---------------------------------------------------------------- session timeout (pure)
def test_session_expiry_rules():
    from fap.identity.session import is_session_expired
    now = 10_000.0
    assert is_session_expired(now - 100 * 60, now, 60, remember=False) is True    # idle past timeout
    assert is_session_expired(now - 30 * 60, now, 60, remember=False) is False     # within window
    assert is_session_expired(now - 100 * 60, now, 60, remember=True) is False     # remembered
    assert is_session_expired(now - 100 * 60, now, 0, remember=False) is False      # timeout disabled
    assert is_session_expired(None, now, 60, remember=False) is False               # no login stamp
