"""
Pure-Python calculation helpers for reports.
No database calls — all inputs are plain Python dicts/lists.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from dateutil.relativedelta import relativedelta


# ---------------------------------------------------------------------------
# Cash Flow Forecast
# ---------------------------------------------------------------------------

FREQUENCY_DELTA = {
    "WEEKLY": timedelta(weeks=1),
    "BIWEEKLY": timedelta(weeks=2),
    "SEMI_MONTHLY": timedelta(days=15),
    "ANNUALLY": None,  # handled separately
    "UNKNOWN": None,
}


def _monthly_delta():
    return relativedelta(months=1)


def _step_occurrence(last_date: date, frequency: str) -> Optional[date]:
    """One cadence step from ``last_date``. None for unknown cadences."""
    freq = frequency.upper()
    if freq == "MONTHLY":
        return last_date + _monthly_delta()
    if freq == "SEMI_MONTHLY":
        return last_date + timedelta(days=15)
    if freq == "ANNUALLY":
        return last_date + relativedelta(years=1)
    delta = FREQUENCY_DELTA.get(freq)
    if delta:
        return last_date + delta
    return None


def next_occurrence(last_date: date, frequency: str) -> Optional[date]:
    """Return the expected next date for a recurring stream — exactly one
    cadence step from ``last_date``. Use :func:`next_future_occurrence`
    when you want the next charge that hasn't already happened."""
    if not last_date or not frequency:
        return None
    return _step_occurrence(last_date, frequency)


def next_future_occurrence(
    last_date: date, frequency: str, *, today: Optional[date] = None
) -> Optional[date]:
    """Return the next charge date on or after ``today``.

    Plaid's ``last_date`` can lag the current date by several cadences (the
    next charge hasn't posted yet, or the stream paused for a while), so a
    single delta step from ``last_date`` may still be in the past. We
    advance in cadence-sized steps until we land on or after ``today``.

    Used by:
      * UI ``Recurring`` page so "Next payment" never displays a past date.
      * ``recurring_tomorrow`` notification producer so the alert fires
        even when last_date is many cadences behind.
    """
    if not last_date or not frequency:
        return None
    horizon = today or date.today()
    nxt = _step_occurrence(last_date, frequency)
    if nxt is None:
        return None
    # Hard cap: WEEKLY over 20 years = ~1040 steps. 2000 catches pathological
    # data without ever looping forever.
    for _ in range(2000):
        if nxt >= horizon:
            return nxt
        candidate = _step_occurrence(nxt, frequency)
        if candidate is None or candidate <= nxt:
            return nxt
        nxt = candidate
    return nxt


def build_forecast(
    streams: List[Dict[str, Any]], days: int = 30
) -> List[Dict[str, Any]]:
    """
    Build a list of upcoming bill entries for outflow streams.
    Returns entries sorted by date, within today..today+days window.
    """
    today = date.today()
    cutoff = today + timedelta(days=days)
    entries = []

    for stream in streams:
        if not stream.get("is_active"):
            continue
        if (stream.get("status") or "").upper() == "TOMBSTONED":
            # Plaid keeps returning streams for a while after they stop; do not
            # extrapolate future bills for streams explicitly marked stopped.
            continue
        if stream.get("direction") != "outflow":
            continue
        last_date = stream.get("last_date")
        if not last_date:
            continue
        if isinstance(last_date, str):
            last_date = date.fromisoformat(last_date)

        next_date = next_occurrence(last_date, stream.get("frequency") or "")
        if next_date and today <= next_date <= cutoff:
            entries.append(
                {
                    "date": next_date,
                    "description": stream.get("user_label") or stream.get("description", ""),
                    "merchant_name": stream.get("merchant_name"),
                    "amount_cents": stream.get("last_amount_cents") or stream.get("average_amount_cents") or 0,
                    "frequency": stream.get("frequency"),
                    "stream_id": stream["id"],
                }
            )

    return sorted(entries, key=lambda e: e["date"])


# ---------------------------------------------------------------------------
# Financial Health Score
# ---------------------------------------------------------------------------

def compute_health_score(
    total_debt_cents: int,
    annual_income_cents: int,
    monthly_income_cents: int,
    monthly_expenses_cents: int,
    total_credit_limit_cents: int,
    total_credit_balance_cents: int,
    liquid_balance_cents: int,
    avg_monthly_expenses_cents: int,
    has_overdue: bool,
    mortgage_loan_cents: int = 0,
) -> Dict[str, Any]:
    """Produce the health score and advice string from pre-aggregated inputs.

    Contract (see ``docs/reports-math.md``):

    - ``total_debt_cents`` is **credit-card debt only**. Mortgages and
      installment loans are passed in via ``mortgage_loan_cents`` and
      surfaced in the advice without contributing to the DTI penalty.
      This matches the user expectation that a home mortgage shouldn't
      tank their score.
    - ``monthly_income_cents`` / ``monthly_expenses_cents`` must be
      computed over **equal windows** (3-month averages over completed
      months). ``annual_income_cents`` is the real 12-month sum so DTI is
      stable.
    """
    score = 100
    advice_parts = []

    # Debt-to-income ratio (lower is better). Uses credit-card principal vs.
    # real 12-month income.
    dti = None
    if annual_income_cents and annual_income_cents > 0:
        dti = total_debt_cents / annual_income_cents
        if dti > 0.43:
            score -= 25
            advice_parts.append("High debt-to-income ratio (>43%). Focus on paying down debt.")
        elif dti > 0.30:
            score -= 10
            advice_parts.append("Moderate debt-to-income ratio. Consider reducing debt.")

    # Credit utilization (lower is better)
    utilization = None
    if total_credit_limit_cents and total_credit_limit_cents > 0:
        utilization = total_credit_balance_cents / total_credit_limit_cents
        if utilization > 0.75:
            score -= 20
            advice_parts.append("Credit utilization is very high (>75%). Pay down credit cards.")
        elif utilization > 0.30:
            score -= 10
            advice_parts.append("Credit utilization above 30%. Try to keep it under 30%.")

    # Savings rate
    savings_rate = None
    if monthly_income_cents and monthly_income_cents > 0:
        savings_rate = (monthly_income_cents - monthly_expenses_cents) / monthly_income_cents
        if savings_rate < 0:
            score -= 20
            advice_parts.append("Spending exceeds income this month.")
        elif savings_rate < 0.10:
            score -= 10
            advice_parts.append("Savings rate below 10%. Try to save at least 10-20% of income.")

    # Emergency fund (liquid / avg monthly expenses)
    emergency_months = None
    if avg_monthly_expenses_cents and avg_monthly_expenses_cents > 0:
        emergency_months = liquid_balance_cents / avg_monthly_expenses_cents
        if emergency_months < 1:
            score -= 20
            advice_parts.append("Emergency fund covers less than 1 month of expenses.")
        elif emergency_months < 3:
            score -= 10
            advice_parts.append("Build emergency fund to cover 3-6 months of expenses.")

    # Overdue accounts
    if has_overdue:
        score -= 15
        advice_parts.append("You have overdue accounts. Make minimum payments immediately.")

    # Mortgage / installment loans are tracked but excluded from DTI. Surface
    # the balance so the user knows the score isn't ignoring it.
    if mortgage_loan_cents and mortgage_loan_cents > 0:
        advice_parts.append(
            f"Mortgage/loan balance of ${mortgage_loan_cents / 100:,.0f} is tracked but excluded from DTI."
        )

    score = max(0, min(100, score))

    if score >= 80:
        label, color = "Excellent", "#22c55e"
    elif score >= 60:
        label, color = "Good", "#84cc16"
    elif score >= 40:
        label, color = "Fair", "#f59e0b"
    else:
        label, color = "Needs Attention", "#ef4444"

    advice = " ".join(advice_parts) if advice_parts else "Your finances look healthy. Keep it up!"

    return {
        "score": score,
        "label": label,
        "color": color,
        "debt_to_income": round(dti, 3) if dti is not None else None,
        "credit_utilization": round(utilization, 3) if utilization is not None else None,
        "savings_rate": round(savings_rate, 3) if savings_rate is not None else None,
        "emergency_fund_months": round(emergency_months, 1) if emergency_months is not None else None,
        "has_overdue": has_overdue,
        "mortgage_loan_cents": mortgage_loan_cents,
        "advice": advice,
    }
