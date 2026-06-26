from __future__ import annotations

import ipaddress

from app import allowlist


def test_parse_allowed_networks_parses_mixed_ipv4_and_ipv6() -> None:
    networks = allowlist.parse_allowed_networks("10.0.0.0/8, 192.168.1.1, 2001:db8::/32")
    assert networks == [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("192.168.1.1/32"),
        ipaddress.ip_network("2001:db8::/32"),
    ]


def test_parse_allowed_networks_ignores_blank_entries() -> None:
    assert allowlist.parse_allowed_networks(" , ,10.0.0.0/8, ") == [ipaddress.ip_network("10.0.0.0/8")]


def test_parse_allowed_networks_skips_invalid_entries() -> None:
    assert allowlist.parse_allowed_networks("not-an-ip,10.0.0.0/8") == [ipaddress.ip_network("10.0.0.0/8")]


def test_parse_allowed_networks_empty_string_yields_no_networks() -> None:
    assert allowlist.parse_allowed_networks("") == []


def test_is_allowed_ip_within_network() -> None:
    assert allowlist.is_allowed("10.1.2.3", [ipaddress.ip_network("10.0.0.0/8")]) is True


def test_is_allowed_ip_outside_network() -> None:
    assert allowlist.is_allowed("192.168.1.1", [ipaddress.ip_network("10.0.0.0/8")]) is False


def test_is_allowed_missing_source_ip() -> None:
    assert allowlist.is_allowed(None, [ipaddress.ip_network("10.0.0.0/8")]) is False


def test_is_allowed_empty_networks() -> None:
    assert allowlist.is_allowed("10.1.2.3", []) is False


def test_is_allowed_malformed_source_ip() -> None:
    assert allowlist.is_allowed("not-an-ip", [ipaddress.ip_network("10.0.0.0/8")]) is False
