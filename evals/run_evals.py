"""
Evaluation runner for ChainOps.

Runs every scenario in evals/scenarios.json through the real workflow
(graph, validation, governance) on its own fresh copy of the seed
database, checks the result against the expected outcome, and reports
metrics.

    python evals/run_evals.py                 # offline: rule baselines, no API key needed
    python evals/run_evals.py --llm live      # real LLM for every agent that is not fault-injected

What is checked (deterministic assertions only):
  * status, decision type, quantity, risk level, approval routing
  * specific agent fields (e.g. demand.demand_risk)
  * that invalid inputs stop before any agent runs
  * that injected faults are detected (invalid output / disagreement flagged)
  * governance outcomes: executed, rejected, retried, no duplicate orders

LLM free text is never compared with exact strings. In live mode one
explicitly defined criterion is applied to the coordinator's explanation:
it must mention the actual stock level ("grounded"). There is no
LLM-as-judge: its scores would be non-deterministic and are not needed
for the properties being tested.

Results are written to evals/results/latest_<mode>.json and .md.
"""

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402
import db_init  # noqa: E402
import db_service  # noqa: E402
import governance  # noqa: E402
import llm_config  # noqa: E402
import workflow  # noqa: E402
from graph import AGENT_NODES  # noqa: E402
from models import DecisionRecord, PurchaseOrder  # noqa: E402
from pydantic import ValidationError  # noqa: E402

SCENARIO_FILE = ROOT / "evals" / "scenarios.json"
RESULTS_DIR = ROOT / "evals" / "results"
AGENTS = ["demand", "inventory", "risk", "logistics", "coordinator"]


def load_scenarios(path: Path = SCENARIO_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["scenarios"]


@contextmanager
def fresh_database():
    """Point the app at a brand-new seeded SQLite file for one scenario."""
    previous = str(db_service.engine.url)
    with tempfile.TemporaryDirectory() as tmp:
        db_service.configure(f"sqlite:///{Path(tmp, 'eval.db').as_posix()}")
        db_init.init_database()
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):  # seed prints a banner
            db_init.seed_data(db_service.engine)
        try:
            yield
        finally:
            db_service.engine.dispose()
            db_service.configure(previous)


def _resolve_time(value: str) -> str:
    now = datetime.now(timezone.utc)
    match = re.fullmatch(r"now(?:-(\d+)h)?", value)
    if match:
        return (now - timedelta(hours=int(match.group(1) or 0))).isoformat()
    return value


def _install_mocks(spec: dict | None):
    if not spec:
        llm_config.set_llm_override(None)
        return

    def fake(agent: str, prompt: str, offline_response: str) -> str:
        if agent not in spec:
            # Unmocked agents answer as they normally would in this mode.
            if llm_config.resolve_mode() == "live":
                return llm_config.get_llm().invoke(prompt).content
            return offline_response
        answer = spec[agent]
        if isinstance(answer, dict) and "raise" in answer:
            raise {"TimeoutError": TimeoutError, "ConnectionError": ConnectionError}.get(
                answer["raise"], RuntimeError)("simulated LLM failure")
        return answer

    llm_config.set_llm_override(fake)


def _po_count() -> int:
    with db_service.get_session() as s:
        return s.query(PurchaseOrder).count()


def _record_count() -> int:
    with db_service.get_session() as s:
        return s.query(DecisionRecord).count()


def _get(record: dict, dotted: str):
    agent, field = dotted.split(".", 1)
    source = record.get("final_decision") if agent == "coordinator" else (record.get("agent_outputs") or {}).get(agent)
    return (source or {}).get(field)


def run_scenario(sc: dict) -> dict:
    """Run one scenario and return {id, passed, checks, observed, latency_ms}."""
    exp = sc["expected"]
    checks: list[tuple[str, bool, str]] = []
    observed: dict = {}

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    with fresh_database():
        _install_mocks(sc.get("llm"))
        try:
            pos_before = _po_count()
            inp = sc["input"]
            started = time.perf_counter()
            record = None

            if inp["type"] == "cycle":
                overlay = inp.get("overlay")
                record = workflow.run_cycle(inp["product_id"], trigger="SCENARIO" if overlay else "MANUAL",
                                            overlay=overlay)
            else:
                payload = {**inp["event"], "occurred_at": _resolve_time(inp["event"]["occurred_at"])}
                try:
                    responses = [workflow.process_event(dict(payload)) for _ in range(inp.get("repeat", 1))]
                    record = responses[0]
                    observed["duplicate_flags"] = [r.get("duplicate") for r in responses]
                except ValidationError as exc:
                    observed["schema_error"] = exc.errors()[0]["msg"]

            latency_ms = round((time.perf_counter() - started) * 1000, 1)

            if "schema_error" in exp:
                check("schema validation rejected payload", "schema_error" in observed, observed.get("schema_error", ""))
                return _result(sc, checks, observed, latency_ms)

            observed.update(status=record["status"], risk_level=record.get("risk_level"),
                            decision=(record.get("final_decision") or {}).get("decision_type"),
                            quantity=((record.get("final_decision") or {}).get("details") or {}).get("quantity"))
            agents_ran = [t["node"] for t in record.get("agent_trace") or [] if t["node"] in AGENT_NODES]
            observed["agents_ran"] = agents_ran

            if "status" in exp:
                check("status", record["status"] == exp["status"], f"{record['status']} vs {exp['status']}")
            if "decision_type" in exp:
                check("decision_type", observed["decision"] == exp["decision_type"], f"{observed['decision']}")
            if "quantity" in exp:
                check("quantity", observed["quantity"] == exp["quantity"], f"{observed['quantity']}")
            if "risk_level" in exp:
                check("risk_level", record.get("risk_level") == exp["risk_level"], f"{record.get('risk_level')}")
            if "approval_required" in exp:
                check("approval_routing", bool(record.get("approval_required")) == exp["approval_required"],
                      f"{record.get('approval_required')}")
            if "validation_status" in exp:
                check("validation_status", record.get("validation_status") == exp["validation_status"], "")
            if "agents_ran" in exp:
                check("agents_ran" if exp["agents_ran"] else "no agent ran on invalid/untriggered input",
                      bool(agents_ran) == exp["agents_ran"], f"{agents_ran}")
            if "error_codes" in exp:
                codes = [e["code"] for e in (record.get("validation_report") or {}).get("errors", [])]
                check("validation error codes", all(c in codes for c in exp["error_codes"]), f"{codes}")
            for dotted, value in (exp.get("agent_fields") or {}).items():
                check(f"field {dotted}", _get(record, dotted) == value, f"{_get(record, dotted)}")
            for text in exp.get("reason_contains", []):
                check(f"reason mentions '{text}'", any(text in r for r in record.get("risk_reasons") or []), "")
            for agent in exp.get("invalid_outputs", []):
                meta = (record.get("final_decision") if agent == "coordinator"
                        else (record.get("agent_outputs") or {}).get(agent, {})).get("meta", {})
                check(f"{agent} invalid output detected", meta.get("output_valid") is False, "")
            for dotted in exp.get("disagreements", []):
                agent, field = dotted.split(".")
                meta = (record.get("final_decision") if agent == "coordinator"
                        else (record.get("agent_outputs") or {}).get(agent, {})).get("meta", {})
                check(f"{dotted} disagreement flagged", field in (meta.get("disagreements") or {}), "")
            if "duplicate_detected" in exp:
                check("duplicate detected", observed.get("duplicate_flags", [])[1:] == [True] * (len(observed["duplicate_flags"]) - 1)
                      and len(observed["duplicate_flags"]) > 1, f"{observed.get('duplicate_flags')}")
            if "decision_records" in exp:
                check("decision records", _record_count() == exp["decision_records"], f"{_record_count()}")

            # Follow-up human / execution actions
            then = sc.get("then") or {}
            did = record["decision_id"]
            if then.get("action") in ("approve", "approve_twice"):
                if then.get("fail_execution_once"):
                    original = db_service.add_purchase_order

                    def failing(*a, **k):
                        db_service.add_purchase_order = original  # fail only once
                        raise ConnectionError("simulated database outage during execution")
                    db_service.add_purchase_order = failing
                after = governance.approve(did, "eval-reviewer")
                observed["after_approve"] = after["status"]
                if "intermediate_status" in exp:
                    check("intermediate status", after["status"] == exp["intermediate_status"], after["status"])
                    check("no PO written by failed execution", _po_count() == pos_before, "")
                if then.get("retry"):
                    after = governance.retry_execution(did)
                if then["action"] == "approve_twice":
                    try:
                        governance.approve(did, "eval-reviewer")
                        observed["second_action"] = "accepted"
                    except governance.InvalidTransition:
                        observed["second_action"] = "rejected"
                    check("second approval rejected", observed["second_action"] == "rejected", "")
            elif then.get("action") == "reject":
                governance.reject(did, "eval-reviewer", "not convinced")
                try:
                    governance.execute(did)
                    observed["execute_after_reject"] = "executed"
                except governance.InvalidTransition:
                    observed["execute_after_reject"] = "blocked"
                check("rejected decision cannot execute", observed["execute_after_reject"] == "blocked", "")

            final = governance.get_record(did)
            observed["final_status"] = final["status"]
            if "final_status" in exp:
                check("final status", final["status"] == exp["final_status"], final["status"])
            if "purchase_orders_created" in exp:
                created = _po_count() - pos_before
                observed["purchase_orders_created"] = created
                check("purchase orders created", created == exp["purchase_orders_created"], f"{created}")

            # Metrics inputs
            observed["metas"] = {a: ((final.get("final_decision") if a == "coordinator"
                                      else (final.get("agent_outputs") or {}).get(a)) or {}).get("meta")
                                 for a in AGENTS}
            explanation = (final.get("final_decision") or {}).get("explanation", "")
            stock = ((final.get("snapshot") or {}).get("inventory") or {}).get("quantity")
            if final.get("final_decision") and stock is not None:
                observed["grounded"] = str(stock) in explanation
            observed["cycle_latency_ms"] = final.get("latency_ms")
            return _result(sc, checks, observed, latency_ms)
        except Exception as exc:  # a crash is a failed scenario, not a crashed eval run
            check("scenario ran without crashing", False, f"{type(exc).__name__}: {exc}")
            return _result(sc, checks, observed, None)
        finally:
            llm_config.set_llm_override(None)


def _result(sc, checks, observed, latency_ms):
    return {"id": sc["id"], "name": sc["name"], "category": sc["category"],
            "passed": all(ok for _, ok, _ in checks) and bool(checks),
            "checks": [{"check": n, "passed": ok, "detail": d} for n, ok, d in checks],
            "observed": observed, "latency_ms": latency_ms, "expected": sc["expected"]}


def compute_metrics(results: list[dict], scenarios: list[dict]) -> dict:
    by_id = {s["id"]: s for s in scenarios}

    def rate(pairs):
        pairs = list(pairs)
        return {"correct": sum(pairs), "total": len(pairs)}

    def field_match(key, observed_key):
        return rate(r["observed"].get(observed_key) == r["expected"][key]
                    for r in results if key in r["expected"] and "status" in r["observed"])

    metas = [m for r in results for m in (r["observed"].get("metas") or {}).values() if m]
    injected = {r["id"] for r in results if by_id[r["id"]].get("llm")}
    clean_metas = [m for r in results if r["id"] not in injected for m in (r["observed"].get("metas") or {}).values() if m]
    invalid_inputs = [r for r in results if r["category"] == "data_validation"]
    cycle_latencies = [r["observed"]["cycle_latency_ms"] for r in results if r["observed"].get("cycle_latency_ms")]
    grounded = [r["observed"]["grounded"] for r in results if "grounded" in r["observed"]]

    return {
        "scenarios_passed": rate(r["passed"] for r in results),
        "risk_classification": field_match("risk_level", "risk_level"),
        "decision_agreement": field_match("decision_type", "decision"),
        "approval_routing": rate(
            bool(r["observed"].get("status") == "PENDING_APPROVAL") == r["expected"]["approval_required"]
            for r in results if "approval_required" in r["expected"] and "status" in r["observed"]),
        "validation_enforcement": rate(
            ("schema_error" in r["observed"]) or (not r["observed"].get("agents_ran") and r["observed"].get("decision") is None)
            for r in invalid_inputs),
        "structured_output_validity_clean_runs": rate(m.get("output_valid") is not False for m in clean_metas),
        "llm_rule_disagreements_clean_runs": sum(len(m.get("disagreements") or {}) for m in clean_metas),
        "injected_faults_detected": rate(
            all(c["passed"] for c in r["checks"] if "detected" in c["check"] or "disagreement" in c["check"])
            for r in results if r["id"] in injected),
        "workflow_completion": rate(r["observed"].get("final_status") not in (None, "FAILED")
                                    for r in results if "schema_error" not in r["expected"]),
        "errors": sum(1 for r in results for c in r["checks"] if c["check"] == "scenario ran without crashing"),
        "cycle_latency_ms": {
            "p50": round(statistics.median(cycle_latencies), 1) if cycle_latencies else None,
            "max": max(cycle_latencies) if cycle_latencies else None,
        },
        "grounded_explanations": rate(grounded),
        "agent_outputs_checked": len(metas),
    }


def write_report(mode: str, results: list[dict], metrics: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (RESULTS_DIR / f"latest_{mode}.json").write_text(
        json.dumps({"mode": mode, "generated_at": stamp, "metrics": metrics, "results": results}, indent=2, default=str),
        encoding="utf-8")

    def pct(m):
        return f"{m['correct']}/{m['total']}" + (f" ({m['correct'] / m['total']:.0%})" if m["total"] else "")

    lines = [
        f"# ChainOps evaluation ({mode} mode)", "",
        f"Generated {stamp} by `python evals/run_evals.py --llm {mode}`. Each scenario ran on a fresh seed database.", "",
        "| Metric | Result |", "|---|---|",
        f"| Scenarios passed | {pct(metrics['scenarios_passed'])} |",
        f"| Risk classification | {pct(metrics['risk_classification'])} |",
        f"| Decision agreement with expected outcome | {pct(metrics['decision_agreement'])} |",
        f"| Human-approval routing | {pct(metrics['approval_routing'])} |",
        f"| Validation enforcement (invalid input stopped before agents) | {pct(metrics['validation_enforcement'])} |",
        f"| Structured output validity (runs without injected faults) | {pct(metrics['structured_output_validity_clean_runs'])} |",
        f"| LLM vs rule disagreements (runs without injected faults) | {metrics['llm_rule_disagreements_clean_runs']} |",
        f"| Injected faults detected | {pct(metrics['injected_faults_detected'])} |",
        f"| Workflow completion | {pct(metrics['workflow_completion'])} |",
        f"| Crashed scenarios | {metrics['errors']} |",
        f"| Grounded coordinator explanations (mention actual stock) | {pct(metrics['grounded_explanations'])} |",
        f"| Cycle latency p50 / max | {metrics['cycle_latency_ms']['p50']} ms / {metrics['cycle_latency_ms']['max']} ms |",
        "", "| ID | Scenario | Category | Result | Failed checks |", "|---|---|---|---|---|",
    ]
    for r in results:
        failed = "; ".join(f"{c['check']} ({c['detail']})" for c in r["checks"] if not c["passed"]) or ""
        lines.append(f"| {r['id']} | {r['name']} | {r['category']} | {'PASS' if r['passed'] else 'FAIL'} | {failed} |")
    path = RESULTS_DIR / f"latest_{mode}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="Run the ChainOps evaluation suite")
    parser.add_argument("--llm", choices=["offline", "live"], default="offline")
    parser.add_argument("--only", nargs="*", help="scenario ids to run")
    args = parser.parse_args()

    config.LLM_MODE = args.llm
    llm_config.check_configuration()
    scenarios = [s for s in load_scenarios() if not args.only or s["id"] in args.only]

    results = []
    for sc in scenarios:
        result = run_scenario(sc)
        results.append(result)
        print(f"{'PASS' if result['passed'] else 'FAIL'}  {sc['id']}  {sc['name']}")
        for c in result["checks"]:
            if not c["passed"]:
                print(f"        failed: {c['check']} ({c['detail']})")

    metrics = compute_metrics(results, scenarios)
    report = write_report(args.llm, results, metrics)
    print(f"\n{metrics['scenarios_passed']['correct']}/{metrics['scenarios_passed']['total']} scenarios passed. "
          f"Report: {report.relative_to(ROOT)}")
    sys.exit(0 if metrics["scenarios_passed"]["correct"] == metrics["scenarios_passed"]["total"] else 1)


if __name__ == "__main__":
    main()
