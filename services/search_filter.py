import re

def matches(expense: tuple, query: str) -> bool:
    """
    Check if expense matches the search query.
    Supports: amount ranges (100..300), amount ops (>100, <=200), date ranges, date equals/prefix, category substring.

    Args:
        expense: tuple (id, category, amount, date, source)
        query: search query string

    Returns:
        bool: True if expense matches query
    """
    if not query.strip():
        return True

    _, category, amount, date, *_ = expense
    tokens = query.split()
    category_lower = category.lower()
    ok_all = True

    for token in tokens:
        token_lower = token.lower()

        # Amount range: 100..300
        range_match = re.match(r'^(\d+(?:[\.,]\d+)?)\.\.(\d+(?:[\.,]\d+)?)$', token_lower)
        if range_match:
            try:
                lo = float(range_match.group(1).replace(',', '.'))
                hi = float(range_match.group(2).replace(',', '.'))
                if not (lo <= amount <= hi):
                    ok_all = False
                    break
                continue
            except ValueError:
                ok_all = False
                break

        # Amount operation: >100, <=200, =50, <100, >=200
        op_match = re.match(r'^(>=|<=|>|<|=)?\s*(\d+(?:[\.,]\d+)?)$', token_lower)
        if op_match:
            try:
                op = op_match.group(1) or '='
                val = float(op_match.group(2).replace(',', '.'))

                match op:
                    case '>':
                        if not (amount > val):
                            ok_all = False
                            break
                    case '<':
                        if not (amount < val):
                            ok_all = False
                            break
                    case '>=':
                        if not (amount >= val):
                            ok_all = False
                            break
                    case '<=':
                        if not (amount <= val):
                            ok_all = False
                            break
                    case '=':
                        if not (amount == val):
                            ok_all = False
                            break
                continue
            except ValueError:
                ok_all = False
                break

        # Date range: 2025-08..2025-09 or 2025-08-01..2025-08-15
        date_range_match = re.match(r'^(\d{4}-\d{2}(?:-\d{2})?)\.\.(\d{4}-\d{2}(?:-\d{2})?)$', token_lower)
        if date_range_match:
            lo, hi = date_range_match.group(1), date_range_match.group(2)
            if not (lo <= date <= hi):
                ok_all = False
                break
            continue

        # Date equals or prefix: 2025-08 or =2025-08-02
        date_match = re.match(r'^=?\d{4}-\d{2}(?:-\d{2})?$', token_lower)
        if date_match:
            val = token_lower.lstrip('=')
            if not date.startswith(val):
                ok_all = False
                break
            continue

        # Default: category contains (substring search)
        if token_lower not in category_lower:
            ok_all = False
            break

    return ok_all
