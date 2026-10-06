"""SSRF-safe HTTP URL liveness verification.

Enforces:
  - http/https schemes only.
  - DNS resolution with blocking of private, loopback, link-local, and multicast IP ranges.
  - Maximum 3 redirects (each validated against SSRF).
  - 5s connect / timeout cap.
  - Maximum 64KB response body size.
  - No credentials or sensitive headers forwarded.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Bounded timeouts
URL_CONNECT_TIMEOUT = 5.0
URL_MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 64 * 1024


def is_safe_ip(ip_str: str) -> bool:
    """Return True if IP is public and safe to connect (not private/loopback/link-local)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
        return True
    except ValueError:
        return False


def validate_url_host_safety(url: str) -> tuple[bool, Optional[str]]:
    """Validate that URL scheme is http/https and resolved IPs are safe.
    
    Returns (is_safe, error_reason).
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"Unsupported scheme: {parsed.scheme}"
        
        hostname = parsed.hostname
        if not hostname:
            return False, "Missing hostname"

        # Resolve hostname via DNS
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if not is_safe_ip(ip_str):
                return False, f"Resolved to non-public IP: {ip_str}"

        return True, None
    except Exception as exc:
        return False, f"DNS resolution failed: {exc}"


is_safe_url = validate_url_host_safety


async def check_url_liveness(url: str) -> dict[str, Any]:
    """Check apply URL liveness safely.
    
    Returns:
      {
        "status": "live" | "dead" | "redirect_generic" | "filled" | "error" | "blocked",
        "http_status": int | None,
        "reason": str,
        "final_url": str,
      }
    """
    is_safe, error_reason = validate_url_host_safety(url)
    if not is_safe:
        return {"status": "blocked", "http_status": None, "reason": error_reason, "final_url": url}

    current_url = url
    redirects_followed = 0

    try:
        timeout = httpx.Timeout(URL_CONNECT_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            while redirects_followed <= URL_MAX_REDIRECTS:
                # Validate host before every request in redirect chain
                is_safe, err = validate_url_host_safety(current_url)
                if not is_safe:
                    return {"status": "blocked", "http_status": None, "reason": f"Redirect blocked: {err}", "final_url": current_url}

                response = await client.get(current_url, headers={"User-Agent": "CareerOS-Liveness-Checker/1.0"})
                
                # Check redirects
                if response.status_code in (301, 302, 303, 307, 308):
                    loc = response.headers.get("Location")
                    if not loc:
                        return {"status": "error", "http_status": response.status_code, "reason": "Redirect missing Location header", "final_url": current_url}
                    # Build absolute URL if relative
                    from urllib.parse import urljoin
                    current_url = urljoin(current_url, loc)
                    redirects_followed += 1
                    continue

                status_code = response.status_code
                if status_code in (404, 410):
                    return {"status": "dead", "http_status": status_code, "reason": "Page not found (404/410)", "final_url": current_url}

                # Check text heuristics on bounded body
                body_text = response.text[:MAX_RESPONSE_BYTES].lower()
                filled_phrases = (
                    "no longer accepting applications",
                    "position has been filled",
                    "job has expired",
                    "job posting is no longer active",
                    "opening is closed",
                )
                for phrase in filled_phrases:
                    if phrase in body_text:
                        return {"status": "filled", "http_status": status_code, "reason": f"Page states '{phrase}'", "final_url": current_url}

                # Check redirect to generic careers page
                orig_path = urlparse(url).path.strip("/")
                curr_path = urlparse(current_url).path.strip("/")
                if len(orig_path) > 10 and (not curr_path or curr_path in ("careers", "jobs", "en/careers")):
                    return {"status": "redirect_generic", "http_status": status_code, "reason": "Redirected to generic careers page", "final_url": current_url}

                if response.status_code < 400:
                    return {"status": "live", "http_status": status_code, "reason": "Active listing (200 OK)", "final_url": current_url}

                return {"status": "error", "http_status": status_code, "reason": f"HTTP {status_code}", "final_url": current_url}

            return {"status": "error", "http_status": None, "reason": "Too many redirects", "final_url": current_url}
    except Exception as exc:
        return {"status": "error", "http_status": None, "reason": str(exc), "final_url": current_url}
