"""Shared fixtures for shell-script tests: a PATH-shimmed fake-bin directory.

Lets tests assert what a script *calls* (docker, git, tailscale, sudo) and in
what order, without touching real infra. See HLD "Key Design Decisions":
pytest is the sole test runner across Python and shell.
"""
import stat

import pytest


@pytest.fixture
def fake_bin(tmp_path):
    """Returns (bin_dir, add) where add(name, body) writes an executable
    fake command `name` whose shell body is `body`."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()

    def add(name: str, body: str) -> None:
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return bin_dir, add


@pytest.fixture
def call_log(tmp_path):
    """Path fake commands can append their invocation to, for assertions."""
    return tmp_path / "calls.log"
