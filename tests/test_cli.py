"""Tests for CLI safety guards around local-only services."""

import pytest

from endnote_mcp.cli import _is_loopback_host


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_is_loopback_host_accepts_local_bindings(host):
    assert _is_loopback_host(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.25", "example.com"])
def test_is_loopback_host_rejects_non_local_bindings(host):
    assert _is_loopback_host(host) is False
