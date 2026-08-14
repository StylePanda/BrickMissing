from __future__ import annotations

import ipaddress

TRUSTED_PROXY_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request) -> str:
    """Accept forwarding data only from the local reverse proxy."""
    peer = _valid_ip(request.META.get("REMOTE_ADDR", ""))
    if peer is None:
        return "unknown"
    peer_address = ipaddress.ip_address(peer)
    if any(peer_address in network for network in TRUSTED_PROXY_NETWORKS):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded and "," not in forwarded:
            candidate = _valid_ip(forwarded)
            if candidate is not None:
                return candidate
    return peer
