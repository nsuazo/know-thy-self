"""Request guard for a no-login LAN app.

1. Host check (blocks DNS rebinding): a web page on some other site can point its own domain at
   this server's LAN address and then read the journal from your browser. Those requests arrive
   with the attacker's domain in the Host header, so only local-looking hosts are accepted: IP
   addresses, localhost, single-label names (tower), and .local / .lan / .home / .home.arpa /
   .internal / .localdomain names. Add anything else (a reverse-proxy domain, a Tailscale name)
   to ALLOWED_HOSTS, or set ALLOWED_HOSTS=* to turn the check off.
2. Origin check (blocks cross-site writes): a browser sends an Origin header with every POST/PUT.
   If it names a different site than the one being written to, the request is refused.
"""
import ipaddress
from urllib.parse import urlsplit

from .config import settings

LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _split_host(value: str) -> str:
    """'Tower.local:8480' -> 'tower.local', '[::1]:8480' -> '::1'."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def host_allowed(host: str) -> bool:
    name = _split_host(host)
    if not name:
        return False
    if "*" in settings.allowed_hosts or name in settings.allowed_hosts:
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return name == "localhost" or "." not in name or name.endswith(LOCAL_SUFFIXES)


def _netloc(value: str, scheme: str) -> str:
    """Host plus port, with the scheme's default port removed, for comparing origins."""
    default = {"http": "80", "https": "443"}.get(scheme, "")
    value = value.strip().lower()
    return value[: -len(default) - 1] if default and value.endswith(":" + default) else value


def origin_matches(origin: str, host: str, forwarded_host: str | None) -> bool:
    parts = urlsplit(origin)
    if not parts.netloc:
        return False  # "null" origins (sandboxed frames, file://) are never this app
    want = _netloc(parts.netloc, parts.scheme)
    candidates = [host] + ([forwarded_host.split(",")[0]] if forwarded_host else [])
    return any(_netloc(c, parts.scheme) == want for c in candidates)


async def _deny(send, status: int, message: str) -> None:
    body = message.encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class RequestGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if not host_allowed(host):
            return await _deny(
                send, 400,
                f"Know Thy Self refused the host name '{_split_host(host)}'. If that is how you reach "
                "this server, add it to the ALLOWED_HOSTS environment variable (comma-separated).",
            )
        origin = headers.get("origin")
        if scope["method"] in UNSAFE_METHODS and origin is not None:
            if not origin_matches(origin, host, headers.get("x-forwarded-host")):
                return await _deny(send, 403, "Cross-site request refused.")
        return await self.app(scope, receive, send)
