from __future__ import annotations

import ipaddress

from aws_lambda_powertools import Logger

logger = Logger()

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_allowed_networks(raw: str) -> list[IpNetwork]:
    networks: list[IpNetwork] = []
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid allowlist entry", extra={"entry": candidate})
    return networks


def is_allowed(source_ip: str | None, networks: list[IpNetwork]) -> bool:
    if not source_ip or not networks:
        return False
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return False
    return any(address in network for network in networks)
