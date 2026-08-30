"""Stealth HTTP client using curl_cffi to bypass Cloudflare/DataDome TLS fingerprint blocks."""

from __future__ import annotations

import logging
from typing import Any

from curl_cffi.requests import Session

logger = logging.getLogger(__name__)

_session = Session()

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
        return _session.get(
            url,
            headers=headers or {},
            timeout=timeout,
            impersonate=IMPERSONATE,
            **kwargs,
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
        return _session.post(
            url,
            headers=headers or {},
            timeout=timeout,
            impersonate=IMPERSONATE,
            **kwargs,
        )
    except Exception as exc:
        logger.warning("stealth_post failed for %s: %s", url, exc)
        return None
