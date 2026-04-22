from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

"""SSRF-hardened HTTP fetch for optional URL context in chat (Skuld-style)."""

class WebFetchError(Exception):
    pass


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise WebFetchError("HTTP redirects are not allowed for web fetch")


def _blocked_host(hostname: str) -> bool:
    h = (hostname or "").lower().strip()
    if not h or h == "localhost":
        return True
    if h.endswith(".local") or h.endswith(".internal"):
        return True
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b, _, _ = (int(x) for x in parts)
        if a == 10 or a == 127:
            return True
        if a == 169 and b == 254:
            return True
        if a == 192 and b == 168:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
    return False


def _canonical_http_url(parsed) -> str:
    """Rebuild URL from validated components only (mitigate user-controlled URL tricks)."""
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise WebFetchError("Only http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise WebFetchError("URL must not include credentials")
    host = parsed.hostname or ""
    if _blocked_host(host):
        raise WebFetchError("Host is not allowed for web fetch")
    netloc = host
    if parsed.port:
        if scheme == "http" and parsed.port != 80:
            netloc = f"{host}:{parsed.port}"
        elif scheme == "https" and parsed.port != 443:
            netloc = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def fetch_public_text(url: str, *, max_bytes: int = 500_000, timeout_sec: float = 15.0) -> str:
    """GET public http(s) URL; blocks obvious private/link-local targets and redirects."""
    parsed = urlparse(url.strip())
    clean = _canonical_http_url(parsed)
    req = Request(
        clean,
        headers={"User-Agent": "TarkaCollaborationBridge/1.0"},
        method="GET",
    )
    opener = build_opener(_NoRedirects())
    try:
        with opener.open(req, timeout=timeout_sec) as resp:
            data = resp.read(max_bytes + 1)
    except HTTPError as e:
        raise WebFetchError(f"HTTP {e.code}: {e.reason}") from e
    except URLError as e:
        raise WebFetchError(str(e.reason or e)) from e
    if len(data) > max_bytes:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace")
