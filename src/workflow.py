"""
Runs decision cycles and records them.

Entry points (all return the stored decision record as a dict):

  run_cycle / arun_cycle        one cycle for a product, optionally with an
                                overlay (MANUAL or SCENARIO trigger)
  process_event / aprocess_event
                                the event pipeline: idempotency -> event rules
                                -> trigger rule -> cycle with the event overlay

Order of operations for a cycle:
  1. check the LLM configuration (fail fast with a clear message)
  2. create a RECEIVED decision record
  3. run the LangGraph graph, timing every node
  4. store snapshot, validation report, agent outputs, risk and reasons,
     and move the record to the status chosen by the graph
  5. AUTO_APPROVED decisions are executed through governance.execute()

Everything runs synchronously inside the call; there is no background
queue. A cycle takes milliseconds offline and a few seconds with an LLM.
"""

import asyncio
import logging
import time

import governance
import llm_config
from db_service import read_supply_chain_snapshot
from events import check_event_rules, evaluate_trigger, parse_event, to_overlay
from graph import AGENT_NODES, create_supply_chain_graph
from overlay import SnapshotOverlay

log = logging.getLogger("chainops.workflow")

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = create_supply_chain_graph()
    return _graph


def _merge(state: dict, update: dict) -> None:
    """Apply one node's update to our copy of the state (same rules as the reducers)."""
    for key, value in (update or {}).items():
        if key == "agent_outputs" and isinstance(value, dict):
            state.setdefault("agent_outputs", {}).update(value)
        else:
            state[key] = value


def _summarise_failure(exc: Exception, node: str | None) -> dict:
    # No traceback in the record or API response; the log has the type.
    return {"stage": "workflow", "last_completed_node": node, "type": type(exc).__name__,
            "message": str(exc)[:300]}


async def arun_cycle(product_id: int, *, trigger: str = "MANUAL", overlay: SnapshotOverlay | dict | None = None,
                     dry_run: bool = False, event=None, decision_id: str | None = None) -> dict:
    llm_config.check_configuration()
    llm_mode = "mock" if llm_config._override else llm_config.resolve_mode()
    overlay_model = SnapshotOverlay(**overlay) if isinstance(overlay, dict) else overlay
    overlay_dict = overlay_model.model_dump(exclude_defaults=True) if overlay_model else None

    if decision_id is None:
        decision_id, _ = governance.create_record(
            trigger=trigger, product_id=product_id,
            input_payload={"overlay": overlay_dict} if overlay_dict else None,
            dry_run=dry_run, llm_mode=llm_mode)

    started = time.perf_counter()
    state: dict = {
        "product_id": product_id,
        "overlay": overlay_dict,
        "db_snapshot": {},
        "agent_outputs": {},
        "final_decision": None,
        "decision_risk": None,
        "human_feedback": None,
    }
    trace: list[dict] = []
    current_node = None

    try:
        last = time.perf_counter()
        async for update in _get_graph().astream(state, stream_mode="updates"):
            for node_name, node_update in update.items():
                now = time.perf_counter()
                trace.append({"node": node_name, "duration_ms": round((now - last) * 1000, 1)})
                last = now
                current_node = node_name
                _merge(state, node_update)
    except Exception as exc:
        log.error("decision_cycle_failed", extra={"fields": {
            "decision_id": decision_id, "last_completed_node": current_node, "error": type(exc).__name__}})
        governance.finish_record(
            decision_id, governance.FAILED, agent_trace=trace,
            agent_outputs=state.get("agent_outputs"), snapshot=state.get("db_snapshot") or None,
            error=_summarise_failure(exc, current_node),
            latency_ms=int((time.perf_counter() - started) * 1000))
        return governance.get_record(decision_id)

    status = state.get("approval_status") or governance.FAILED
    governance.finish_record(
        decision_id, status,
        snapshot=state.get("db_snapshot"),
        validation_status=(state.get("validation") or {}).get("status"),
        validation_report=state.get("validation"),
        agent_trace=trace,
        agent_outputs=state.get("agent_outputs"),
        final_decision=state.get("final_decision"),
        risk_level=state.get("decision_risk"),
        risk_reasons=state.get("risk_reasons"),
        approval_required=(status == governance.PENDING_APPROVAL),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    log.info("decision_cycle_completed", extra={"fields": {
        "decision_id": decision_id, "product_id": product_id, "status": status,
        "risk": state.get("decision_risk"), "agents": [t["node"] for t in trace if t["node"] in AGENT_NODES]}})

    if status == governance.AUTO_APPROVED:
        return governance.execute(decision_id)
    return governance.get_record(decision_id)


def run_cycle(product_id: int, **kwargs) -> dict:
    """Synchronous wrapper for scripts, Streamlit and tests."""
    return asyncio.run(arun_cycle(product_id, **kwargs))


async def aprocess_event(payload) -> dict:
    """
    Process one business event. `payload` is a dict (validated here) or an
    already-validated event model. Returns the decision record plus a
    `duplicate` flag and, when no cycle ran, a `trigger_reason`.
    """
    event = parse_event(payload) if isinstance(payload, dict) else payload
    llm_config.check_configuration()
    llm_mode = "mock" if llm_config._override else llm_config.resolve_mode()

    decision_id, created = governance.create_record(
        trigger="EVENT", product_id=event.product_id, event_type=event.event_type,
        event_id=event.event_id, input_payload=event.model_dump(mode="json"), llm_mode=llm_mode)
    if not created:
        # Webhook retry or double send: same answer, no second cycle.
        return {**governance.get_record(decision_id), "duplicate": True}

    # Event-level rules and reference checks happen before any agent runs.
    errors = check_event_rules(event)
    baseline = None
    try:
        baseline = read_supply_chain_snapshot(event.product_id)
    except ValueError:
        errors.append({"code": "INCONSISTENT_REFERENCE", "field": "product_id",
                       "message": f"product {event.product_id} does not exist"})
    if errors:
        governance.finish_record(
            decision_id, governance.VALIDATION_FAILED, validation_status="FAILED",
            validation_report={"status": "FAILED", "errors": errors, "warnings": []},
            risk_reasons=[f"{e['code']}: {e['message']}" for e in errors])
        return {**governance.get_record(decision_id), "duplicate": False}

    triggered, reason = evaluate_trigger(event, baseline)
    if not triggered:
        governance.finish_record(decision_id, governance.NOT_TRIGGERED, risk_reasons=[reason])
        return {**governance.get_record(decision_id), "duplicate": False, "trigger_reason": reason}

    record = await arun_cycle(event.product_id, trigger="EVENT", overlay=to_overlay(event),
                              event=event, decision_id=decision_id)
    return {**record, "duplicate": False, "trigger_reason": reason}


def process_event(payload) -> dict:
    return asyncio.run(aprocess_event(payload))
