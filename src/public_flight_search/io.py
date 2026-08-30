"""Bounded JSON input for local files or public HTTPS provider endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class SourceError(ValueError):
    """Raised when an input source is unsafe or malformed."""


def _read_bounded(response: Any, max_bytes: int) -> bytes:
    payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise SourceError("source exceeds the configured byte limit")
    return payload


def load_json_source(
    source: str, *, timeout: int = 15, max_bytes: int = 1_000_000
) -> list[dict[str, Any]]:
    parts = urlsplit(source)
    try:
        if parts.scheme:
            if parts.scheme != "https" or not parts.netloc:
                raise SourceError("only HTTPS network sources are supported")
            request = Request(source, headers={"User-Agent": "public-flight-search/1"})
            with urlopen(request, timeout=timeout) as response:
                payload = _read_bounded(response, max_bytes)
        else:
            path = Path(source)
            if path.stat().st_size > max_bytes:
                raise SourceError("source exceeds the configured byte limit")
            payload = path.read_bytes()
        parsed = json.loads(payload)
    except SourceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceError("unable to load a valid JSON source") from exc

    if isinstance(parsed, dict):
        parsed = parsed.get("offers")
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise SourceError("JSON source must be a list of offer objects")
    return parsed
