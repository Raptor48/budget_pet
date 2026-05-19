"""Single source of truth for the user-facing app version.

The string is returned by ``/healthz`` and rendered in the System status
bar on the Settings page. Bump it as part of any branch-level version
change (e.g. cutting v2.6 → update here, the UI follows automatically).

Distinct from FastAPI's `version=...` parameter (which feeds the OpenAPI
spec and is more of an API contract pin). Both can be set from this
constant when convenient.
"""

APP_VERSION = "v2.5"
