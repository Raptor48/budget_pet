"""reports_include_plaid_sandbox() — default ties to PLAID_ENV."""

import pytest

from web.env_flags import reports_include_plaid_sandbox


def test_explicit_true(monkeypatch):
    monkeypatch.setenv("REPORTS_INCLUDE_PLAID_SANDBOX", "true")
    monkeypatch.setenv("PLAID_ENV", "production")
    assert reports_include_plaid_sandbox() is True


def test_explicit_false_overrides_sandbox(monkeypatch):
    monkeypatch.setenv("REPORTS_INCLUDE_PLAID_SANDBOX", "false")
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    assert reports_include_plaid_sandbox() is False


def test_default_true_when_plaid_env_sandbox(monkeypatch):
    monkeypatch.delenv("REPORTS_INCLUDE_PLAID_SANDBOX", raising=False)
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    assert reports_include_plaid_sandbox() is True


def test_default_false_when_plaid_env_production(monkeypatch):
    monkeypatch.delenv("REPORTS_INCLUDE_PLAID_SANDBOX", raising=False)
    monkeypatch.setenv("PLAID_ENV", "production")
    assert reports_include_plaid_sandbox() is False


def test_default_false_when_plaid_env_unset(monkeypatch):
    monkeypatch.delenv("REPORTS_INCLUDE_PLAID_SANDBOX", raising=False)
    monkeypatch.delenv("PLAID_ENV", raising=False)
    assert reports_include_plaid_sandbox() is False
