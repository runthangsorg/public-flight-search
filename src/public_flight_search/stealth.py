"""Stealth HTTP client using curl_cffi to bypass Cloudflare/DataDome TLS fingerprint blocks."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from curl_cffi.requests import Session as _CurlSession
    _session = _CurlSession()
    _HAS_CURL_CFFI = True
except ImportError:
    import urllib.request
    import urllib.parse
    import json as _json

    class _FallbackResponse:
        def __init__(self, status_code: int, content: bytes):
            self.status_code = status_code
            self.content = content
            self.text = content.decode("utf-8", errors="replace")

        def json(self) -> Any:
            return _json.loads(self.text)

    class _FallbackSession:
        def get(self, url: str, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None, timeout: int = 15, **kwargs: Any) -> _FallbackResponse:
            if params:
                query = urllib.parse.urlencode(params)
                url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _FallbackResponse(resp.getcode(), resp.read())

        def post(self, url: str, headers: dict[str, str] | None = None, data: Any = None, json: Any = None, timeout: int = 15, **kwargs: Any) -> _FallbackResponse:
            body = None
            req_headers = dict(headers or {})
            if json is not None:
                body = _json.dumps(json).encode("utf-8")
                req_headers["Content-Type"] = "application/json"
            elif data is not None:
                if isinstance(data, dict):
                    body = urllib.parse.urlencode(data).encode("utf-8")
                elif isinstance(data, str):
                    body = data.encode("utf-8")
                else:
                    body = data
            req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _FallbackResponse(resp.getcode(), resp.read())

    _session = _FallbackSession()
    _HAS_CURL_CFFI = False

IMPERSONATE = "chrome124"


def stealth_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    **kwargs: Any,
):
    """GET with Chrome TLS fingerprint impersonation. Returns response or None on error."""
    try:
        kwargs_to_pass = dict(kwargs)
        if _HAS_CURL_CFFI and "impersonate" not in kwargs_to_pass:
            kwargs_to_pass["impersonate"] = IMPERSONATE
        return _session.get(
            url,
            headers=headers or {},
            timeout=timeout,
            **kwargs_to_pass,
        )
    except Exception as exc:
        logger.warning("stealth_get failed for %s: %s", url, exc)
        return None


def stealth_post(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    **kwargs: Any,
):
    """POST with Chrome TLS fingerprint impersonation. Returns response or None on error."""
    try:
        kwargs_to_pass = dict(kwargs)
        if _HAS_CURL_CFFI and "impersonate" not in kwargs_to_pass:
            kwargs_to_pass["impersonate"] = IMPERSONATE
        return _session.post(
            url,
            headers=headers or {},
            timeout=timeout,
            **kwargs_to_pass,
        )
    except Exception as exc:
        logger.warning("stealth_post failed for %s: %s", url, exc)
        return None
