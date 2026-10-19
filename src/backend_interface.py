"""
Backend interface for UI.
Single entry point that triggers the LangGraph workflow.
UI calls this, never touches agents directly.
"""

import db_init
from workflow import run_cycle


def run_one_cycle(product_id: int = 1, overlay: dict | None = None, dry_run: bool = False) -> dict:
    """
    Execute one complete decision cycle for a product.

    Args:
        product_id: Product to analyze (1, 2, or 3)
        overlay: Optional what-if changes (see overlay.SnapshotOverlay).
                 A cycle with an overlay is a scenario and always a dry run.
        dry_run: Record the decision but never write a purchase order.

    Returns:
        The stored decision record (see governance.to_dict), plus the keys
        the original UI used (db_snapshot, decision_risk, human_feedback).
    """
    db_init.ensure_database()
    record = run_cycle(
        product_id,
        trigger="SCENARIO" if overlay else "MANUAL",
        overlay=overlay,
        dry_run=dry_run or bool(overlay),
    )
    return {
        **record,
        "db_snapshot": record.get("snapshot") or {},
        "decision_risk": record.get("risk_level"),
        "human_feedback": record.get("status"),
    }
