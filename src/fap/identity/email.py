"""Email delivery as a plugin family (no hard-coded SMTP).

An ``EmailProvider`` turns a message into an actual send. ``ConsoleEmailProvider``
(the development default) writes the invitation link, recipient, subject and body
to the log so the whole invitation flow works with no mail server. The
``GraphEmailProvider`` sends through Microsoft Graph behind the SAME interface;
SMTP or SendGrid providers can be added later as one more subclass.

Nothing here is Streamlit-specific; the provider is injected into the
AdministrationService by bootstrap.
"""
from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass

from fap.core.plugin import Plugin, PluginInfo, PluginRegistry

logger = logging.getLogger("fap.identity.email")


@dataclass(slots=True)
class EmailMessage:
    to: str
    subject: str
    body: str
    link: str = ""


class EmailProvider(Plugin):
    available: bool = True

    @abstractmethod
    def send(self, message: EmailMessage) -> bool:
        """Deliver the message. Returns True on success; never raises (a failed
        send must not break the calling admin action)."""


email_registry: PluginRegistry[EmailProvider] = PluginRegistry("email_provider")


# ---------------------------------------------------------------- console (dev)
@email_registry.register
class ConsoleEmailProvider(EmailProvider):
    info = PluginInfo(id="console", name="Console email (development)", category="email")

    def send(self, message: EmailMessage) -> bool:
        logger.info(
            "\n==================== EMAIL (console provider) ====================\n"
            "To:      %s\nSubject: %s\nLink:    %s\n------------------------------------------------------------------\n"
            "%s\n==================================================================",
            message.to, message.subject, message.link or "(none)", message.body)
        return True


# ---------------------------------------------------------------- Microsoft Graph
@email_registry.register
class GraphEmailProvider(EmailProvider):
    """Send via Microsoft Graph ``/users/{sender}/sendMail`` using an app-only
    (client-credentials) token. Requires ``requests`` and a configured app
    registration with ``Mail.Send`` application permission. Degrades to
    unavailable when the dependency or configuration is missing."""
    info = PluginInfo(id="microsoft_graph", name="Microsoft Graph", category="email")

    def __init__(self, tenant_id: str = "", client_id: str = "", client_secret: str = "",
                 sender: str = "") -> None:
        self._tenant = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._sender = sender

    @property
    def available(self) -> bool:  # type: ignore[override]
        try:
            import requests  # noqa: F401
        except Exception:
            return False
        return bool(self._tenant and self._client_id and self._client_secret and self._sender)

    def _token(self) -> str | None:
        import requests
        resp = requests.post(
            f"https://login.microsoftonline.com/{self._tenant}/oauth2/v2.0/token",
            data={"client_id": self._client_id, "client_secret": self._client_secret,
                  "scope": "https://graph.microsoft.com/.default",
                  "grant_type": "client_credentials"}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("access_token")

    def send(self, message: EmailMessage) -> bool:
        if not self.available:
            logger.warning("GraphEmailProvider unavailable (missing requests or config).")
            return False
        try:
            import requests
            token = self._token()
            if not token:
                return False
            payload = {"message": {
                "subject": message.subject,
                "body": {"contentType": "HTML", "content": message.body},
                "toRecipients": [{"emailAddress": {"address": message.to}}]},
                "saveToSentItems": True}
            r = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{self._sender}/sendMail",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload, timeout=20)
            r.raise_for_status()
            return True
        except Exception:
            logger.exception("Microsoft Graph sendMail failed")
            return False


def invitation_message(*, to: str, platform_name: str, inviter: str, role_name: str,
                       link: str) -> EmailMessage:
    """Build the standard invitation email (used by AdministrationService)."""
    subject = f"You have been invited to {platform_name}"
    body = (
        f"<p>{inviter} has invited you to join <b>{platform_name}</b> as "
        f"<b>{role_name}</b>.</p>"
        f"<p>Sign in with your Microsoft work account to accept:</p>"
        f'<p><a href="{link}">{link}</a></p>'
        f"<p>If you did not expect this invitation you can ignore this email.</p>")
    return EmailMessage(to=to, subject=subject, body=body, link=link)


def load_builtin_email_providers() -> None:
    return None
