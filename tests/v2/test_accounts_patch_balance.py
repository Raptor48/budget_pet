"""Cash wallet designation rules for balance PATCH."""
from web.accounts.cash_wallet import is_designated_cash_wallet


def test_designated_cash_wallet_positive():
    row = {
        "name": "Cash",
        "type": "depository",
        "subtype": "cash",
        "plaid_account_id": None,
        "is_active": True,
    }
    assert is_designated_cash_wallet(row) is True


def test_not_designated_when_plaid_linked():
    row = {
        "name": "Cash",
        "type": "depository",
        "subtype": "cash",
        "plaid_account_id": "plaid-123",
        "is_active": True,
    }
    assert is_designated_cash_wallet(row) is False


def test_not_designated_when_wrong_subtype():
    row = {
        "name": "Cash",
        "type": "depository",
        "subtype": "checking",
        "plaid_account_id": None,
        "is_active": True,
    }
    assert is_designated_cash_wallet(row) is False
