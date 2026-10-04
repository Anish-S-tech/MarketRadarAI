"""Deterministic comparison of structured pricing tables."""

from typing import Any


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def _fmt(price: float | None, currency: str, period: str) -> str:
    if price is None:
        return "custom pricing"
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency, f"{currency} ")
    amount = f"{price:,.2f}".rstrip("0").rstrip(".")
    return f"{sym}{amount}/{period}"


def compare_pricing(
    old: dict[str, Any] | None, new: dict[str, Any] | None, competitor: str = ""
) -> list[dict]:
    """Returns a list of structured changes, each with a human-readable `description`."""
    old_plans = {_norm(p["name"]): p for p in (old or {}).get("plans", [])}
    new_plans = {_norm(p["name"]): p for p in (new or {}).get("plans", [])}
    who = f"{competitor} " if competitor else ""
    changes: list[dict] = []

    for key, np in new_plans.items():
        op = old_plans.get(key)
        if op is None:
            changes.append(
                {
                    "type": "plan_added",
                    "plan": np["name"],
                    "new_price": np.get("price"),
                    "description": f"{who}added plan '{np['name']}' at "
                    f"{_fmt(np.get('price'), np.get('currency', 'USD'), np.get('period', 'month'))}",
                }
            )
            continue
        o_price, n_price = op.get("price"), np.get("price")
        if o_price != n_price or op.get("period") != np.get("period"):
            pct = None
            if o_price and n_price:
                pct = round((n_price - o_price) / o_price * 100, 1)
            direction = "raised" if (pct or 0) > 0 else "cut" if (pct or 0) < 0 else "changed"
            desc = (
                f"{who}{direction} '{np['name']}' price from "
                f"{_fmt(o_price, op.get('currency', 'USD'), op.get('period', 'month'))} to "
                f"{_fmt(n_price, np.get('currency', 'USD'), np.get('period', 'month'))}"
                + (f" ({pct:+.1f}%)" if pct is not None else "")
            )
            changes.append(
                {
                    "type": "price_changed",
                    "plan": np["name"],
                    "old_price": o_price,
                    "new_price": n_price,
                    "pct_change": pct,
                    "description": desc,
                }
            )
        of = {_norm(f) for f in op.get("features", [])}
        nf = {_norm(f): f for f in np.get("features", [])}
        added = [nf[k] for k in nf if k not in of]
        removed = [f for f in op.get("features", []) if _norm(f) not in nf]
        if added:
            changes.append(
                {
                    "type": "features_added",
                    "plan": np["name"],
                    "features": added,
                    "description": f"{who}added to '{np['name']}': {', '.join(added[:5])}",
                }
            )
        if removed:
            changes.append(
                {
                    "type": "features_removed",
                    "plan": np["name"],
                    "features": removed,
                    "description": f"{who}removed from '{np['name']}': {', '.join(removed[:5])}",
                }
            )

    for key, op in old_plans.items():
        if key not in new_plans:
            changes.append(
                {
                    "type": "plan_removed",
                    "plan": op["name"],
                    "old_price": op.get("price"),
                    "description": f"{who}removed plan '{op['name']}'",
                }
            )
    return changes
