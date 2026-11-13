"""
The position book: how many shares each client holds, and what they cost.

Quantities here are SETTLED positions - what the depository register shows.
That is what decides who is entitled to a corporate action.
"""

import pandas as pd


class PositionBook:
    def __init__(self, opening_positions: pd.DataFrame):
        # key: (account_id, ticker) -> {"quantity": int, "cost": total cost in Rs}
        self._book = {}
        for _, row in opening_positions.iterrows():
            self._book[(row["account_id"], row["ticker"])] = {
                "quantity": int(row["quantity"]),
                "cost": float(row["quantity"] * row["avg_cost"]),
            }

    # ---------- reading ----------
    def quantity(self, account_id, ticker) -> int:
        return self._book.get((account_id, ticker), {"quantity": 0})["quantity"]

    def cost(self, account_id, ticker) -> float:
        return self._book.get((account_id, ticker), {"cost": 0.0})["cost"]

    def holders(self, ticker) -> dict:
        """All accounts with a positive holding in a ticker -> quantity."""
        return {acc: pos["quantity"] for (acc, tkr), pos in self._book.items()
                if tkr == ticker and pos["quantity"] > 0}

    def total_cost(self) -> float:
        return sum(p["cost"] for p in self._book.values())

    def to_frame(self) -> pd.DataFrame:
        rows = [{"account_id": a, "ticker": t, "quantity": p["quantity"],
                 "total_cost": round(p["cost"], 2),
                 "avg_cost": round(p["cost"] / p["quantity"], 4) if p["quantity"] else 0.0}
                for (a, t), p in self._book.items() if p["quantity"] > 0]
        return pd.DataFrame(rows).sort_values(["account_id", "ticker"]).reset_index(drop=True)

    # ---------- changing ----------
    def _pos(self, account_id, ticker):
        return self._book.setdefault((account_id, ticker), {"quantity": 0, "cost": 0.0})

    def apply_trade(self, account_id, ticker, side, quantity, price):
        pos = self._pos(account_id, ticker)
        if side == "BUY":
            pos["quantity"] += quantity
            pos["cost"] += quantity * price
        else:  # SELL - cost is released at the average cost
            avg = pos["cost"] / pos["quantity"] if pos["quantity"] else 0.0
            pos["quantity"] -= quantity
            pos["cost"] -= avg * quantity

    def add_shares(self, account_id, ticker, quantity, cost_added=0.0):
        pos = self._pos(account_id, ticker)
        pos["quantity"] += quantity
        pos["cost"] += cost_added

    def set_cost(self, account_id, ticker, new_cost):
        self._pos(account_id, ticker)["cost"] = new_cost
