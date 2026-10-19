"""Approval state machine, idempotency and execution (uses the per-test SQLite DB)."""

import threading

import pytest

import db_service
import governance as g


def _pending(dry_run=False, decision=None, status=g.PENDING_APPROVAL, product_id=2):
    did, created = g.create_record(trigger="MANUAL", product_id=product_id, dry_run=dry_run)
    assert created
    g.finish_record(did, status, final_decision=decision or {
        "decision_type": "REORDER", "details": {"supplier_id": 1, "quantity": 150, "expedite": True},
        "explanation": "test"})
    return did


def test_approve_executes_and_writes_one_po(po_count):
    before = po_count()
    did = _pending()
    record = g.approve(did, "alice", "ok")
    assert record["status"] == g.EXECUTED
    assert record["reviewed_by"] == "alice" and record["reviewed_at"] and record["executed_at"]
    assert record["execution_result"]["action"] == "PURCHASE_ORDER_CREATED"
    assert po_count() == before + 1


def test_reject_never_executes(po_count):
    before = po_count()
    did = _pending()
    assert g.reject(did, "bob", "too risky")["status"] == g.REJECTED
    with pytest.raises(g.InvalidTransition):
        g.execute(did)
    with pytest.raises(g.InvalidTransition):
        g.approve(did, "bob")
    assert po_count() == before


@pytest.mark.parametrize("status", [g.NO_ACTION_REQUIRED, g.VALIDATION_FAILED, g.NOT_TRIGGERED, g.FAILED])
def test_terminal_statuses_cannot_be_approved_or_executed(status):
    did = _pending(status=status)
    with pytest.raises(g.InvalidTransition):
        g.approve(did, "alice")
    with pytest.raises(g.InvalidTransition):
        g.execute(did)


def test_generated_recommendation_is_not_executed():
    did = _pending()
    record = g.get_record(did)
    assert record["status"] == g.PENDING_APPROVAL
    assert record["execution_result"] is None and record["executed_at"] is None


def test_double_approval_creates_one_po(po_count):
    before = po_count()
    did = _pending()
    g.approve(did, "alice")
    with pytest.raises(g.InvalidTransition) as exc:
        g.approve(did, "alice")
    assert exc.value.current == g.EXECUTED
    assert po_count() == before + 1


def test_concurrent_approvals_execute_once(po_count):
    before = po_count()
    did = _pending()
    outcomes = []

    def attempt():
        try:
            g.approve(did, "racer")
            outcomes.append("ok")
        except g.InvalidTransition:
            outcomes.append("blocked")

    threads = [threading.Thread(target=attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 1
    assert po_count() == before + 1


def test_failed_execution_is_recorded_and_retry_works(po_count, monkeypatch):
    before = po_count()
    did = _pending()
    original = db_service.add_purchase_order

    def boom(*args, **kwargs):
        raise ConnectionError("db went away")
    monkeypatch.setattr(db_service, "add_purchase_order", boom)
    record = g.approve(did, "alice")
    assert record["status"] == g.EXECUTION_FAILED
    assert record["error"]["type"] == "ConnectionError"
    assert po_count() == before  # rolled back

    monkeypatch.setattr(db_service, "add_purchase_order", original)
    assert g.retry_execution(did)["status"] == g.EXECUTED
    assert po_count() == before + 1
    with pytest.raises(g.InvalidTransition):
        g.retry_execution(did)


def test_dry_run_records_but_writes_nothing(po_count):
    before = po_count()
    record = g.approve(_pending(dry_run=True), "alice")
    assert record["status"] == g.EXECUTED
    assert record["execution_result"]["mode"] == "dry_run"
    assert po_count() == before


def test_auto_approved_decision_executes():
    did = _pending(status=g.AUTO_APPROVED)
    assert g.execute(did)["status"] == g.EXECUTED


def test_non_executable_decision_fails_cleanly(po_count):
    before = po_count()
    did = _pending(decision={"decision_type": "REORDER", "details": {"supplier_id": None, "quantity": 0}})
    assert g.approve(did, "alice")["status"] == g.EXECUTION_FAILED
    assert po_count() == before


def test_event_id_is_idempotent():
    first, created1 = g.create_record(trigger="EVENT", product_id=1, event_id="evt-1")
    second, created2 = g.create_record(trigger="EVENT", product_id=1, event_id="evt-1")
    assert created1 and not created2 and first == second


def test_unknown_decision():
    with pytest.raises(g.DecisionNotFound):
        g.get_record("dec_missing")
    with pytest.raises(g.DecisionNotFound):
        g.approve("dec_missing", "alice")
