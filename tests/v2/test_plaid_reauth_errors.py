"""Tests for Plaid Item re-authentication error detection."""

import json

import pytest
from plaid.exceptions import ApiException

from web.plaid.reauth_errors import plaid_error_requires_item_reauth


def _api_exc(body: dict | str) -> ApiException:
    exc = ApiException(status=400, reason="Bad Request")
    exc.body = json.dumps(body) if isinstance(body, dict) else body
    return exc


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_api_exc({"error_code": "ITEM_LOGIN_REQUIRED"}), True),
        (_api_exc({"error_code": "INSUFFICIENT_CREDENTIALS"}), True),
        (_api_exc({"error_code": "ITEM_LOCKED"}), True),
        (_api_exc({"error_code": "USER_SETUP_REQUIRED"}), True),
        (_api_exc({"error_code": "INVALID_ACCESS_TOKEN"}), True),
        (_api_exc({"error_code": "ITEM_NOT_FOUND"}), True),
        (_api_exc({"error_code": "RATE_LIMIT_EXCEEDED"}), False),
        (_api_exc({"error_code": "INTERNAL_SERVER_ERROR"}), False),
        (RuntimeError("ITEM_LOGIN_REQUIRED in message"), True),
        (
            RuntimeError(
                "the login details of this item have changed — use Link's update mode"
            ),
            True,
        ),
        (RuntimeError("unrelated failure"), False),
    ],
)
def test_plaid_error_requires_item_reauth(exc: BaseException, expected: bool) -> None:
    assert plaid_error_requires_item_reauth(exc) is expected


def test_string_body_on_api_exception() -> None:
    exc = ApiException(status=400, reason="x")
    exc.body = '{"error_code": "ITEM_LOGIN_REQUIRED"}'
    assert plaid_error_requires_item_reauth(exc) is True
