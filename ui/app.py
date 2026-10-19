"""
Streamlit UI for the ChainOps multi-agent supply chain control tower.

A thin layer over the backend: every button calls the same functions the
API uses (workflow.run_cycle, governance.approve/reject), so what you see
is what the system recorded. Three tabs:

  Decision cycle      run the agents on the current database state
  Scenario simulator  apply a what-if overlay and compare with the baseline
  Approvals and audit review pending decisions and inspect any record
"""

import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import db_init  # noqa: E402
import governance  # noqa: E402
import llm_config  # noqa: E402
from backend_interface import run_one_cycle  # noqa: E402
from db_service import list_products  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

st.set_page_config(page_title="ChainOps Control Tower", layout="wide")
db_init.ensure_database()

STATUS_HELP = {
    "PENDING_APPROVAL": "Waiting for a human. Nothing has been executed.",
    "APPROVED": "Approved by a reviewer.",
    "AUTO_APPROVED": "Approved by policy (low risk).",
    "EXECUTED": "Action carried out (simulated, see execution result).",
    "EXECUTION_FAILED": "Approved, but execution failed. Nothing was written. Can be retried.",
    "REJECTED": "Rejected by a reviewer. It will never execute.",
    "NO_ACTION_REQUIRED": "The recommendation is HOLD, so there is nothing to execute.",
    "VALIDATION_FAILED": "Input data broke a business rule. No agent ran and nothing was recommended.",
    "NOT_TRIGGERED": "The event was below its trigger threshold. No agent ran.",
    "FAILED": "The workflow raised an error. See the error section.",
}
AGENT_LABELS = [
    ("demand", "Demand agent", ["demand_risk"]),
    ("inventory", "Inventory agent", ["action", "quantity", "capped"]),
    ("risk", "Risk agent", ["supplier_risk", "logistics_risk"]),
    ("logistics", "Logistics agent", ["expedite"]),
]

products = list_products()
product_names = {p["id"]: f"{p['name']} ({p['sku']})" for p in products}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("ChainOps: Multi-Agent Supply Chain Control Tower")
mode = llm_config.resolve_mode()
st.caption(
    "LangGraph workflow with five agents, data validation before any AI call, "
    "and human approval before any order. "
    + ("LLM mode: **live** (OpenRouter)." if mode == "live" else
       "LLM mode: **offline**. No API key is set, so agents answer with their deterministic rule "
       "baselines. Set OPENROUTER_API_KEY to use the LLM.")
)
st.info("Execution is simulated: an approved order is written as a purchase order row in the local "
        "SQLite database. No ERP or supplier system is contacted. Scenario runs never write orders.")


# ---------------------------------------------------------------------------
# Shared rendering
# ---------------------------------------------------------------------------

def review_controls(record: dict, key_prefix: str):
    """Approve / reject buttons for a pending decision."""
    did = record["decision_id"]
    reviewer = st.text_input("Reviewer name", key=f"{key_prefix}_reviewer_{did}", max_chars=64)
    note = st.text_input("Note (optional)", key=f"{key_prefix}_note_{did}", max_chars=500)
    c1, c2 = st.columns(2)
    if c1.button("Approve and execute", key=f"{key_prefix}_approve_{did}", type="primary",
                 disabled=not reviewer.strip()):
        try:
            st.session_state[f"{key_prefix}_record"] = governance.approve(did, reviewer.strip(), note or None)
        except governance.InvalidTransition as exc:
            st.error(str(exc))
        st.rerun()
    if c2.button("Reject", key=f"{key_prefix}_reject_{did}", disabled=not reviewer.strip()):
        try:
            st.session_state[f"{key_prefix}_record"] = governance.reject(did, reviewer.strip(), note or None)
        except governance.InvalidTransition as exc:
            st.error(str(exc))
        st.rerun()
    if not reviewer.strip():
        st.caption("Enter a reviewer name to enable the buttons.")


def render_snapshot(snapshot: dict):
    product = snapshot.get("product", {})
    inventory = snapshot.get("inventory")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Product:** {product.get('name', 'N/A')} ({product.get('sku', 'N/A')})")
        if inventory:
            rop_note = ""
            if inventory.get("demand_multiplier"):
                rop_note = (f" (base {inventory['base_reorder_point']} x demand "
                            f"{inventory['demand_multiplier']})")
            st.markdown(f"**Stock:** {inventory['quantity']} units  \n"
                        f"**Reorder point:** {inventory['reorder_point']}{rop_note}")
        else:
            st.markdown("**Inventory:** no record")
        st.markdown(f"**Open purchase orders:** {len(snapshot.get('purchase_orders', []))}  \n"
                    f"**Shipments in transit:** {len(snapshot.get('shipments', []))}")
    with c2:
        suppliers = snapshot.get("suppliers", [])
        if suppliers:
            st.dataframe(pd.DataFrame(suppliers)[["id", "name", "reliability_score", "lead_time_days"]],
                         hide_index=True, width="stretch")
    if snapshot.get("overlay_changes"):
        st.markdown("**Scenario changes applied:** " + "; ".join(snapshot["overlay_changes"]))


def render_record(record: dict, key_prefix: str):
    """Everything the audit record knows about one decision, top to bottom."""
    status = record["status"]
    final = record.get("final_decision") or {}

    st.subheader(f"Decision {record['decision_id']}")
    m1, m2, m3, m4 = st.columns([2, 1, 1, 1])
    # Long status names get truncated by st.metric, so render it as text.
    m1.caption("Status")
    m1.markdown(f"#### {status}")
    m2.metric("Risk level", record.get("risk_level") or "n/a")
    m3.metric("Human approval required", "Yes" if record.get("approval_required") else "No")
    m4.metric("Validation", record.get("validation_status") or "n/a")
    st.caption(STATUS_HELP.get(status, ""))

    # 1. Input conditions
    with st.expander("1. Input conditions", expanded=False):
        if record.get("input_payload"):
            st.json(record["input_payload"])
        if record.get("snapshot"):
            render_snapshot(record["snapshot"])

    # 2. Validation
    report = record.get("validation_report") or {}
    with st.expander(f"2. Validation: {record.get('validation_status') or 'not run'}",
                     expanded=status == "VALIDATION_FAILED"):
        if report.get("errors"):
            st.error("Errors (cycle stopped before any agent ran)")
            st.dataframe(pd.DataFrame(report["errors"]), hide_index=True, width="stretch")
        if report.get("warnings"):
            st.warning("Data-quality warnings (force human review)")
            st.dataframe(pd.DataFrame(report["warnings"]), hide_index=True, width="stretch")
        if report and not report.get("errors") and not report.get("warnings"):
            st.success("All business rules passed.")

    # 3. Execution sequence
    trace = record.get("agent_trace") or []
    if trace:
        with st.expander("3. Execution sequence", expanded=False):
            st.dataframe(pd.DataFrame(trace), hide_index=True, width="stretch")
            st.caption(f"Total latency: {record.get('latency_ms')} ms, LLM mode: {record.get('llm_mode')}")

    # 4. Individual agents
    outputs = record.get("agent_outputs") or {}
    if any(name in outputs for name, _, _ in AGENT_LABELS):
        st.markdown("**4. Agent recommendations**")
        for name, label, fields in AGENT_LABELS:
            out = outputs.get(name)
            if not out:
                continue
            meta = out.get("meta", {})
            flag = ""
            if meta.get("output_valid") is False:
                flag = " | output invalid, rule fallback used"
            elif meta.get("disagreements"):
                flag = " | disagreed with rule baseline"
            summary = ", ".join(f"{f}={out.get(f)}" for f in fields)
            with st.expander(f"{label}: {summary}{flag}"):
                st.write(out.get("reasoning", ""))
                st.caption(f"Answer source: {meta.get('source')}")
                if meta.get("issues"):
                    st.warning("; ".join(meta["issues"]))
                if meta.get("disagreements"):
                    st.json(meta["disagreements"])

    # 5. Coordinator
    if final:
        st.markdown("**5. Coordinator recommendation**")
        details = final.get("details", {})
        if final.get("decision_type") == "REORDER":
            st.markdown(f"**REORDER** {details.get('quantity')} units from supplier "
                        f"#{details.get('supplier_id')}, expedite: {'yes' if details.get('expedite') else 'no'}")
        else:
            st.markdown("**HOLD**: no order")
        with st.expander("Coordinator reasoning"):
            st.write(final.get("explanation", ""))
            meta = final.get("meta", {})
            if meta.get("issues"):
                st.warning("; ".join(meta["issues"]))
            if meta.get("disagreements"):
                st.json(meta["disagreements"])

    # 6-7. Risk and policy
    if record.get("risk_reasons"):
        st.markdown("**6. Why this risk level / outcome**")
        for reason in record["risk_reasons"]:
            st.markdown(f"- {reason}")

    # 8. Review
    st.markdown("**7. Approval**")
    if status == "PENDING_APPROVAL":
        review_controls(record, key_prefix)
    elif record.get("reviewed_by"):
        verdict = "Rejected" if status == "REJECTED" else "Approved"
        st.markdown(f"{verdict} by **{record['reviewed_by']}** at {record['reviewed_at'][:19]} UTC"
                    + (f": {record['review_note']}" if record.get("review_note") else ""))
    else:
        st.markdown("No human review needed." if status != "AUTO_APPROVED" else "Approved by policy.")

    # 9-10. Execution and errors
    st.markdown("**8. Execution**")
    result = record.get("execution_result")
    if result:
        (st.success if status == "EXECUTED" else st.error)(result.get("message", ""))
    else:
        st.markdown("Not executed.")
    if record.get("error"):
        st.error(f"Error: {record['error']}")
        if status == "EXECUTION_FAILED" and st.button("Retry execution", key=f"{key_prefix}_retry"):
            st.session_state[f"{key_prefix}_record"] = governance.retry_execution(record["decision_id"])
            st.rerun()


def run_and_store(key_prefix: str, product_id: int, overlay: dict | None):
    try:
        with st.spinner("Running the multi-agent workflow..."):
            st.session_state[f"{key_prefix}_record"] = run_one_cycle(product_id, overlay=overlay or None)
    except llm_config.LLMConfigError as exc:
        st.error(str(exc))
    except Exception as exc:  # keep the UI alive; details go to the server log
        st.error(f"Workflow failed: {type(exc).__name__}")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_cycle, tab_sim, tab_audit = st.tabs(["Decision cycle", "Scenario simulator", "Approvals and audit"])

with tab_cycle:
    product_id = st.selectbox("Select product", options=list(product_names), format_func=product_names.get)
    if st.button("Run supply chain decision cycle", type="primary", width="stretch"):
        run_and_store("cycle", product_id, None)
    if st.session_state.get("cycle_record"):
        render_record(st.session_state["cycle_record"], "cycle")
    else:
        st.markdown("Select a product and run a cycle. High-risk recommendations stop at "
                    "PENDING_APPROVAL until someone approves or rejects them.")

with tab_sim:
    st.markdown("Pick a scenario, adjust it if you like, and run it through the real workflow. "
                "Scenario runs are dry runs: approving one records the decision but writes no order.")
    scenario = st.selectbox("Scenario", SCENARIOS, format_func=lambda s: s["name"])
    st.caption(scenario["description"])

    with st.expander("Customise", expanded=False):
        sim_product = st.selectbox("Product", list(product_names), format_func=product_names.get,
                                   index=list(product_names).index(scenario["product_id"]),
                                   key=f"sim_product_{scenario['key']}")
        ov = scenario["overlay"]
        use_qty = st.checkbox("Override stock", value="inventory_quantity" in ov, key=f"q_{scenario['key']}")
        qty = st.number_input("Stock (units, negative values test validation)", value=int(ov.get("inventory_quantity", 100)),
                              step=10, key=f"qv_{scenario['key']}")
        demand = st.slider("Demand multiplier", 0.5, 10.0, float(ov.get("demand_multiplier", 1.0)), 0.25,
                           key=f"d_{scenario['key']}")
        delay = st.slider("Shipment delay (days)", 0, 30, int(ov.get("shipment_delay_days", 0)),
                          key=f"s_{scenario['key']}")
        clear = st.checkbox("Remove open orders and shipments", value=ov.get("clear_purchase_orders", False),
                            key=f"c_{scenario['key']}")
    overlay = {k: v for k, v in ov.items() if k == "supplier_reliability"}
    if use_qty:
        overlay["inventory_quantity"] = int(qty)
    if demand != 1.0:
        overlay["demand_multiplier"] = demand
    if delay:
        overlay["shipment_delay_days"] = delay
    if clear:
        overlay["clear_purchase_orders"] = True
    st.code(f"product_id={sim_product}  overlay={overlay or '{}'}", language="text")

    if st.button("Run scenario", type="primary", width="stretch"):
        run_and_store("sim", sim_product, overlay)

    record = st.session_state.get("sim_record")
    if record:
        snap = record.get("snapshot") or {}
        base = None
        if snap:
            from db_service import read_supply_chain_snapshot
            base = read_supply_chain_snapshot(record["product_id"])
        if base and snap:
            st.markdown("**Baseline vs scenario**")

            def facts(s):
                inv = s.get("inventory") or {}
                etas = ", ".join((sh.get("expected_arrival") or "none")[:10] for sh in s.get("shipments", [])) or "none"
                rel = ", ".join(f"#{x['id']} {x['reliability_score']:.0%}" for x in s.get("suppliers", []))
                return [inv.get("quantity", "missing"), inv.get("reorder_point", "missing"),
                        len(s.get("purchase_orders", [])), etas, rel]

            st.dataframe(pd.DataFrame(
                {"Baseline (database)": facts(base), "Scenario": facts(snap)},
                index=["Stock", "Reorder point", "Open POs", "Shipment ETAs", "Supplier reliability"],
            ).astype(str), width="stretch")
        render_record(record, "sim")

with tab_audit:
    pending = governance.list_records(limit=100, status="PENDING_APPROVAL")
    st.markdown(f"**Pending approval: {len(pending)}**")
    if pending:
        st.dataframe(pd.DataFrame([{
            "decision_id": r["decision_id"], "created_at": r["created_at"][:19], "trigger": r["trigger"],
            "product": product_names.get(r["product_id"], r["product_id"]),
            "action": f"{(r['final_decision'] or {}).get('decision_type')} "
                      f"{((r['final_decision'] or {}).get('details') or {}).get('quantity')}",
            "dry_run": r["dry_run"], "risk": r["risk_level"],
        } for r in pending]), hide_index=True, width="stretch")

    st.markdown("**All decisions**")
    status_filter = st.selectbox("Filter by status", ["(all)"] + sorted(STATUS_HELP))
    rows = governance.list_records(limit=200, status=None if status_filter == "(all)" else status_filter)
    if rows:
        st.dataframe(pd.DataFrame([{
            "decision_id": r["decision_id"], "created_at": r["created_at"][:19], "trigger": r["trigger"],
            "event_type": r["event_type"], "product_id": r["product_id"], "status": r["status"],
            "risk": r["risk_level"], "validation": r["validation_status"], "latency_ms": r["latency_ms"],
        } for r in rows]), hide_index=True, width="stretch")
        chosen = st.selectbox("Inspect decision", [r["decision_id"] for r in rows])
        if chosen:
            if st.session_state.get("audit_record", {}).get("decision_id") != chosen:
                st.session_state["audit_record"] = governance.get_record(chosen)
            render_record(st.session_state["audit_record"], "audit")
    else:
        st.markdown("No decisions recorded yet.")
