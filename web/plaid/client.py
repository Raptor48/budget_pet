"""
Plaid API client wrapper.
"""
import os
import logging
from typing import Optional
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode

logger = logging.getLogger(__name__)

# Plaid environment mapping
_ENV_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "development": plaid.Environment.Production,
    "production": plaid.Environment.Production,
}


def get_plaid_client() -> plaid_api.PlaidApi:
    """Create and return a configured Plaid API client."""
    env_name = os.getenv("PLAID_ENV", "sandbox").lower()
    host = _ENV_MAP.get(env_name, plaid.Environment.Sandbox)

    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": os.getenv("PLAID_CLIENT_ID"),
            "secret": os.getenv("PLAID_SECRET"),
        },
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)


def create_link_token(user_id: str = "default-user") -> dict:
    """Create a Plaid Link token to initialize the Plaid Link UI."""
    client = get_plaid_client()
    request = LinkTokenCreateRequest(
        products=[Products("transactions"), Products("liabilities")],
        client_name="Budget Pet",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
    )
    response = client.link_token_create(request)
    return {"link_token": response["link_token"], "expiration": str(response["expiration"])}


def exchange_public_token(public_token: str) -> dict:
    """Exchange a Plaid public_token for a permanent access_token."""
    client = get_plaid_client()
    request = ItemPublicTokenExchangeRequest(public_token=public_token)
    response = client.item_public_token_exchange(request)
    return {
        "access_token": response["access_token"],
        "item_id": response["item_id"],
    }


def get_transactions_sync(access_token: str, cursor: Optional[str] = None) -> dict:
    """
    Fetch new/modified/removed transactions since the last cursor.
    Returns dict with added, modified, removed lists and next_cursor.
    """
    client = get_plaid_client()

    added, modified, removed = [], [], []
    has_more = True
    next_cursor = cursor

    while has_more:
        request = TransactionsSyncRequest(access_token=access_token)
        if next_cursor:
            request.cursor = next_cursor

        response = client.transactions_sync(request)
        added.extend(response["added"])
        modified.extend(response["modified"])
        removed.extend(response["removed"])
        has_more = response["has_more"]
        next_cursor = response["next_cursor"]

    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "next_cursor": next_cursor,
    }


def get_account_balances(access_token: str) -> list:
    """Fetch current balances for all accounts linked to this item."""
    client = get_plaid_client()
    request = AccountsBalanceGetRequest(access_token=access_token)
    response = client.accounts_balance_get(request)
    return response["accounts"]


def get_liabilities(access_token: str) -> dict:
    """
    Fetch liabilities data: credit cards and loans with APR, min_payment,
    last_payment_date, next_payment_due_date, last_statement_balance.
    Returns dict with 'credit' and 'student' lists (mortgage if applicable).
    Returns empty dict if the item does not have liabilities product.
    """
    client = get_plaid_client()
    try:
        request = LiabilitiesGetRequest(access_token=access_token)
        response = client.liabilities_get(request)
        liabilities = response.get("liabilities", {})
        # Include accounts so sync_liabilities can resolve account_id → name
        return {
            "credit": liabilities.get("credit") or [],
            "student": liabilities.get("student") or [],
            "accounts": response.get("accounts") or [],
        }
    except Exception as e:
        logger.warning("Liabilities fetch failed (item may not have liabilities product): %s", e)
        return {"credit": [], "student": [], "accounts": []}
