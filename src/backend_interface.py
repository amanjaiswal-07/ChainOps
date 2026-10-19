"""
Backend interface for UI.
Single entry point that triggers LangGraph workflow.
UI calls this, never touches agents directly.
"""

import asyncio
import json
import time
from pathlib import Path

from graph import create_supply_chain_graph


# #region agent log
DEBUG_LOG_PATH = Path(__file__).resolve().parents[1] / ".cursor" / "debug.log"


def _agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict | None = None,
    run_id: str = "initial",
) -> None:
    """Lightweight NDJSON logger for debug-mode instrumentation (backend)."""
    payload = {
        "sessionId": "debug-session",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        # Logging failures must never affect business logic
        pass


# #endregion


def run_one_cycle(product_id: int = 1) -> dict:
    """
    Execute one complete decision cycle for a product.

    Args:
        product_id: Product to analyze (1, 2, or 3)

    Returns:
        Structured output with all agent decisions and reasoning
    """
    # #region agent log
    _agent_debug_log(
        hypothesis_id="H3",
        location="src/backend_interface.py:run_one_cycle:start",
        message="Entered run_one_cycle",
        data={"product_id": int(product_id)},
    )
    # #endregion

    # Create graph
    app = create_supply_chain_graph()

    # Initial state
    initial_state = {
        "product_id": product_id,
        "db_snapshot": {},
        "agent_outputs": {},
        "final_decision": None,
        "decision_risk": None,
        "human_feedback": None,
    }

    # Run async workflow synchronously
    async def _run():
        final_state = {}
        async for event in app.astream(initial_state):
            for node_name, node_output in event.items():
                for key, value in node_output.items():
                    if key == "agent_outputs" and key in final_state:
                        final_state["agent_outputs"].update(value)
                    else:
                        final_state[key] = value
        return final_state

    result = asyncio.run(_run())

    # #region agent log
    _agent_debug_log(
        hypothesis_id="H4",
        location="src/backend_interface.py:run_one_cycle:end",
        message="Completed run_one_cycle",
        data={
            "has_final_decision": result.get("final_decision") is not None,
            "keys": list(result.keys()),
        },
    )
    # #endregion

    # Return structured output
    return {
        "db_snapshot": result.get("db_snapshot", {}),
        "agent_outputs": result.get("agent_outputs", {}),
        "final_decision": result.get("final_decision"),
        "decision_risk": result.get("decision_risk"),
        "human_feedback": result.get("human_feedback"),
    }
