"""Brand-asset enrichment package.

Right now this is a thin wrapper around the Brandfetch HTTP API. Lives
outside ``web/plaid/`` because the enrichment also runs for non-Plaid
data (manual cash entries can carry a merchant_name too) and because
the long-term plan is to plug in additional sources (e.g. Google
favicon for the rare case where Brandfetch misses but we know the
domain) without bloating the Plaid module.

Public surface intentionally minimal:

* ``brandfetch`` — low-level HTTP client + helpers (search, get_brand,
  fetch_asset_base64, pick_icon_url, best_match).
* ``service`` — orchestration for the merchant-logo backoff loop.
* ``repo`` — asyncpg repo for the ``merchant_logos`` cache table.
"""
