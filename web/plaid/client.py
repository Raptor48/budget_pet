"""
Plaid API client wrapper — V2.
Supports transactions, liabilities, investments, recurring_transactions, statements.
"""
import logging
import os
from typing import Optional

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.institutions_get_by_id_request_options import InstitutionsGetByIdRequestOptions
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_webhook_update_request import ItemWebhookUpdateRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.personal_finance_category_version import PersonalFinanceCategoryVersion
from plaid.model.transactions_recurring_get_request import TransactionsRecurringGetRequest
from plaid.model.transactions_recurring_get_request_options import TransactionsRecurringGetRequestOptions
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions

from web.plaid.constants import get_plaid_pfc_category_version

logger = logging.getLogger(__name__)

_ENV_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "development": plaid.Environment.Production,
    "production": plaid.Environment.Production,
}

# Only transactions is required — every connected institution must support it.
_PRODUCTS = [
    Products("transactions"),
]

# liabilities moves to required_if_supported so that banks without liabilities
# (credit unions, investment-only accounts, etc.) are still shown in Link.
# investments stays disabled by default until Plaid approves the product.
# recurring_transactions is NOT a link product — data comes from /transactions/recurring/get.
_REQUIRED_IF_SUPPORTED = [
    Products("liabilities"),
]


def _get_optional_products() -> list:
    """Return investments as optional_products when PLAID_ENABLE_INVESTMENTS is true."""
    enable_investments = os.getenv("PLAID_ENABLE_INVESTMENTS", "true").strip().lower()
    if enable_investments in ("1", "true", "yes"):
        return [Products("investments")]
    return []


def _pfc_version_model() -> PersonalFinanceCategoryVersion:
    return PersonalFinanceCategoryVersion(get_plaid_pfc_category_version())


def _transactions_sync_request_options() -> TransactionsSyncRequestOptions:
    return TransactionsSyncRequestOptions(
        personal_finance_category_version=_pfc_version_model(),
    )


def _transactions_recurring_request_options() -> TransactionsRecurringGetRequestOptions:
    return TransactionsRecurringGetRequestOptions(
        personal_finance_category_version=_pfc_version_model(),
    )


def get_plaid_client() -> plaid_api.PlaidApi:
    """Create and return a configured Plaid API client."""
    import certifi
    env_name = os.getenv("PLAID_ENV", "sandbox").lower()
    host = _ENV_MAP.get(env_name, plaid.Environment.Sandbox)
    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": os.getenv("PLAID_CLIENT_ID"),
            "secret": os.getenv("PLAID_SECRET"),
        },
        ssl_ca_cert=certifi.where(),
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)


def create_link_token(
    user_id: str = "default-user",
    access_token: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> dict:
    """
    Create a Plaid Link token.

    ``access_token`` — pass for Link update mode (fix broken connection).
    ``redirect_uri`` — required for OAuth institutions (Chase, BofA, etc.) on mobile.
                       Register this URI in the Plaid Dashboard → API → Allowed redirect URIs.
    """
    client = get_plaid_client()
    # redirect_uri is only passed when configured — sandbox works without it
    effective_redirect = (redirect_uri or os.getenv("PLAID_REDIRECT_URI") or "").strip() or None
    # webhook URL — Plaid sends SYNC_UPDATES_AVAILABLE, ITEM_LOGIN_REQUIRED, etc. here
    # Strip whitespace to avoid INVALID_FIELD errors from trailing spaces in env vars.
    webhook_url = (os.getenv("PLAID_WEBHOOK_URL") or "").strip() or None
    common = dict(
        client_name="Budget Pet",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
    )
    if effective_redirect:
        common["redirect_uri"] = effective_redirect
    if webhook_url:
        common["webhook"] = webhook_url
    if access_token:
        request = LinkTokenCreateRequest(
            access_token=access_token,
            **common,
        )
    else:
        optional = _get_optional_products()
        request = LinkTokenCreateRequest(
            products=_PRODUCTS,
            required_if_supported_products=_REQUIRED_IF_SUPPORTED,
            **({"optional_products": optional} if optional else {}),
            **common,
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
    Fetch new/modified/removed transactions using cursor-based sync.
    Paginates automatically until has_more is False.
    Returns dict with added, modified, removed lists and next_cursor.
    """
    client = get_plaid_client()
    added, modified, removed = [], [], []
    has_more = True
    next_cursor = cursor

    while has_more:
        request = TransactionsSyncRequest(
            access_token=access_token,
            options=_transactions_sync_request_options(),
        )
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
    accounts = response["accounts"]
    # Convert SDK objects to plain dicts
    return [a.to_dict() if hasattr(a, "to_dict") else a for a in accounts]


def get_liabilities(access_token: str) -> dict:
    """
    Fetch liabilities: credit cards, student loans, mortgages.
    Returns empty dicts on error (item may not have liabilities product).
    """
    client = get_plaid_client()
    try:
        request = LiabilitiesGetRequest(access_token=access_token)
        response = client.liabilities_get(request)
        liabilities_obj = response.get("liabilities") or {}
        liab = liabilities_obj.to_dict() if hasattr(liabilities_obj, "to_dict") else liabilities_obj
        accounts = response.get("accounts") or []
        accounts_list = [
            a.to_dict() if hasattr(a, "to_dict") else a for a in accounts
        ]
        return {
            "credit": liab.get("credit") or [],
            "student": liab.get("student") or [],
            "mortgage": liab.get("mortgage") or [],
            "accounts": accounts_list,
        }
    except Exception as exc:
        logger.warning("Liabilities fetch failed (item may not have liabilities): %s", exc)
        return {"credit": [], "student": [], "mortgage": [], "accounts": []}


def get_recurring_transactions(access_token: str, account_ids: Optional[list] = None) -> dict:
    """
    Fetch recurring transaction streams from Plaid.
    Returns dict with inflow_streams and outflow_streams.
    """
    client = get_plaid_client()
    try:
        kwargs: dict = {
            "access_token": access_token,
            "options": _transactions_recurring_request_options(),
        }
        if account_ids:
            kwargs["account_ids"] = account_ids
        request = TransactionsRecurringGetRequest(**kwargs)
        response = client.transactions_recurring_get(request)
        inflow = response.get("inflow_streams") or []
        outflow = response.get("outflow_streams") or []
        return {
            "inflow_streams": [s.to_dict() if hasattr(s, "to_dict") else s for s in inflow],
            "outflow_streams": [s.to_dict() if hasattr(s, "to_dict") else s for s in outflow],
        }
    except Exception as exc:
        logger.warning("Recurring transactions fetch failed: %s", exc)
        return {"inflow_streams": [], "outflow_streams": []}


def get_item_institution_id(access_token: str) -> Optional[str]:
    """
    Fetch the institution_id for a Plaid item.
    Returns None if the call fails or institution_id is unavailable.
    """
    client = get_plaid_client()
    try:
        request = ItemGetRequest(access_token=access_token)
        response = client.item_get(request)
        item = response.get("item") or {}
        item_dict = item.to_dict() if hasattr(item, "to_dict") else item
        return item_dict.get("institution_id")
    except Exception as exc:
        logger.warning("item_get failed: %s", exc)
        return None


def get_institution_metadata(institution_id: str) -> dict:
    """
    Fetch logo (base64 PNG) and primary brand color for an institution.
    Returns dict with keys: logo (str | None), color (str | None).
    Not all institutions provide logos — returns None gracefully.
    """
    client = get_plaid_client()
    try:
        options = InstitutionsGetByIdRequestOptions(include_optional_metadata=True)
        request = InstitutionsGetByIdRequest(
            institution_id=institution_id,
            country_codes=[CountryCode("US")],
            options=options,
        )
        response = client.institutions_get_by_id(request)
        institution = response.get("institution") or {}
        inst_dict = institution.to_dict() if hasattr(institution, "to_dict") else institution
        return {
            "logo": inst_dict.get("logo"),
            "color": inst_dict.get("primary_color"),
        }
    except Exception as exc:
        logger.warning("institutions_get_by_id failed for %s: %s", institution_id, exc)
        return {"logo": None, "color": None}


def update_item_webhook(access_token: str, webhook_url: str) -> bool:
    """
    Update the webhook URL for an existing Plaid Item via /item/webhook/update.
    Must be called after token exchange so existing items pick up the new URL.
    Returns True on success, False on error.
    """
    client = get_plaid_client()
    try:
        request = ItemWebhookUpdateRequest(
            access_token=access_token,
            webhook=webhook_url,
        )
        client.item_webhook_update(request)
        logger.info("Webhook updated for item (access_token prefix: %s...)", access_token[:8])
        return True
    except Exception as exc:
        logger.warning("item_webhook_update failed: %s", exc)
        return False


def get_investment_holdings(access_token: str) -> dict:
    """
    Fetch investment holdings from Plaid.
    Returns dict with holdings and securities lists.
    """
    client = get_plaid_client()
    try:
        request = InvestmentsHoldingsGetRequest(access_token=access_token)
        response = client.investments_holdings_get(request)
        holdings = response.get("holdings") or []
        securities = response.get("securities") or []
        return {
            "holdings": [h.to_dict() if hasattr(h, "to_dict") else h for h in holdings],
            "securities": [s.to_dict() if hasattr(s, "to_dict") else s for s in securities],
        }
    except Exception as exc:
        logger.warning("Investment holdings fetch failed (item may not have investments): %s", exc)
        return {"holdings": [], "securities": []}
