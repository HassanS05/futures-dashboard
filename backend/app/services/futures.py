"""Futures risk/reward calculator.

Direct, faithful port of the original Streamlit prototype's core logic so no
existing functionality is lost — now reusable as a pure service + API.
"""

from __future__ import annotations

from app.models.schemas import FuturesResult, FuturesScenario

CONTRACTS: dict[str, dict[str, float]] = {
    "MGC (Micro Gold Futures)": {"tick_size": 0.10, "tick_value": 1.0},
    "GC (Gold Futures)": {"tick_size": 0.10, "tick_value": 10.0},
    "MNQ (Micro Nasdaq Futures)": {"tick_size": 0.25, "tick_value": 0.50},
    "MES (Micro S&P Futures)": {"tick_size": 0.25, "tick_value": 1.25},
}


def compute(scenario: FuturesScenario) -> FuturesResult:
    spec = CONTRACTS.get(scenario.contract)
    if not spec:
        raise ValueError(f"Unknown contract: {scenario.contract}")
    tick_size = spec["tick_size"]
    tick_value = spec["tick_value"]

    ticks_tp = round(abs(scenario.tp_price - scenario.entry_price) / tick_size)
    ticks_sl = round(abs(scenario.entry_price - scenario.sl_price) / tick_size)
    profit = ticks_tp * tick_value * scenario.quantity
    loss = ticks_sl * tick_value * scenario.quantity

    return FuturesResult(
        contract=scenario.contract,
        ticks_to_tp=ticks_tp,
        ticks_to_sl=ticks_sl,
        potential_profit=round(profit, 2),
        potential_loss=round(loss, 2),
        risk_reward=round(profit / loss, 2) if loss else None,
    )
