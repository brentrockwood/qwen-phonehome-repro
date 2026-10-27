#!/usr/bin/env python3
"""Hardened client for recording a generated destination at the loopback sink.

Every sink-replay path in this repo goes through here, so the README's safety
guarantee holds repo-wide (not just in one script):
- the sink endpoint MUST be loopback, else the replay is refused;
- environment proxies are ignored and redirects are refused, so a replay cannot
  be bounced to an off-box host.

This records intent; it is NOT an egress-policy enforcer for a real agent.
"""
import json
import urllib.request
from urllib.parse import urlsplit

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def is_loopback(sink: str) -> bool:
    return urlsplit(sink).hostname in LOOPBACK


def replay(sink: str, url: str, meta: dict) -> str:
    """Record `url` at the loopback `sink`. Returns a short status string."""
    if not is_loopback(sink):
        return f"refused: sink {sink!r} is not loopback"
    sp = urlsplit(url if "://" in url else "http://" + url)
    if not sp.netloc:
        return "skipped: unparseable url"
    try:
        req = urllib.request.Request(
            sink.rstrip("/") + "/" + sp.netloc + sp.path,
            data=json.dumps(meta).encode(),
            headers={"Host": sp.netloc, "X-Source": meta.get("src", "replay")},
            method="GET")
        with _OPENER.open(req, timeout=5) as r:
            return f"recorded {r.status}"
    except Exception as e:  # sink down, refused redirect, etc. — never fatal
        return f"capture-error: {e}"
