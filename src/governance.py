"""
Decision records, the approval state machine, and execution.

This is the only module that changes a decision's status or performs a
side effect (writing a purchase order).

State machine
-------------
                     +--> NOT_TRIGGERED        (event below threshold)
                     +--> VALIDATION_FAILED    (bad input; no agents ran)
                     +--> FAILED               (workflow error)
    RECEIVED --------+--> NO_ACTION_REQUIRED   (HOLD)
                     +--> AUTO_APPROVED -------+
                     +--> PENDING_APPROVAL     |
                              |                |
                   approve    |    reject      |
                     +--------+--------+       |
                     v                 v       v
                 APPROVED          REJECTED  EXECUTING --> EXECUTED
                     |                          ^   |
                     +--------------------------+   +--> EXECUTION_FAILED
                                                           |  (retry)
                                                           +--> EXECUTING

Every transition is a compare-and-set UPDATE ... WHERE status IN (...).
If two requests race to approve the same decision, exactly one wins and
the other gets InvalidTransition. That is what prevents duplicate
purchase orders on retries or double clicks.

Execution is a *simulation* in the sense that no external ERP or supplier
system is contacted. A non-dry-run execution writes a purchase order row
to the local SQLite database, in the same transaction that marks the
decision EXECUTED, so either both happen or neither does.
"""

import logging
import uuid

from sqlalchemy.exc import IntegrityError

import db_service
from models import DecisionRecord, utcnow

log = logging.getLogger("chainops.governance")

# --- Statuses -------------------------------------------------------------
RECEIVED = "RECEIVED"
NOT_TRIGGERED = "NOT_TRIGGERED"
VALIDATION_FAILED = "VALIDATION_FAILED"
FAILED = "FAILED"
NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
PENDING_APPROVAL = "PENDING_APPROVAL"
AUTO_APPROVED = "AUTO_APPROVED"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
EXECUTING = "EXECUTING"
EXECUTED = "EXECUTED"
EXECUTION_FAILED = "EXECUTION_FAILED"

TRANSITIONS = {
    RECEIVED: {NOT_TRIGGERED, VALIDATION_FAILED, FAILED, NO_ACTION_REQUIRED, PENDING_APPROVAL, AUTO_APPROVED},
    PENDING_APPROVAL: {APPROVED, REJECTED},
    APPROVED: {EXECUTING},
    AUTO_APPROVED: {EXECUTING},
    EXECUTING: {EXECUTED, EXECUTION_FAILED},
    EXECUTION_FAILED: {EXECUTING},
}
TERMINAL = {NOT_TRIGGERED, VALIDATION_FAILED, FAILED, NO_ACTION_REQUIRED, REJECTED, EXECUTED}


class DecisionNotFound(LookupError):
    pass


class InvalidTransition(ValueError):
    def __init__(self, decision_id: str, current: str, attempted: str):
        self.decision_id, self.current, self.attempted = decision_id, current, attempted
        super().__init__(f"decision {decision_id} is {current}; cannot move to {attempted}")


def _allowed_sources(target: str) -> set[str]:
    return {src for src, targets in TRANSITIONS.items() if target in targets}


# --- Serialization ----------------------------------------------------------

_COLUMNS = [c.name for c in DecisionRecord.__table__.columns]


def to_dict(record: DecisionRecord) -> dict:
    data = {}
    for name in _COLUMNS:
        value = getattr(record, name)
        data[name] = value.isoformat() if hasattr(value, "isoformat") else value
    data["decision_id"] = data.pop("id")
    return data


# --- Record lifecycle ---------------------------------------------------------

def new_decision_id() -> str:
    return f"dec_{uuid.uuid4().hex[:12]}"


def create_record(*, trigger: str, product_id: int | None, event_type: str | None = None,
                  event_id: str | None = None, input_payload: dict | None = None,
                  dry_run: bool = False, llm_mode: str | None = None) -> tuple[str, bool]:
    """
    Insert a RECEIVED record. Returns (decision_id, created).

    For events, event_id is UNIQUE: if the same event arrives twice
    (webhook retry), the insert fails and the existing decision is returned
    with created=False, so the event is processed only once.
    """
    decision_id = new_decision_id()
    try:
        with db_service.get_session() as session:
            session.add(DecisionRecord(
                id=decision_id, status=RECEIVED, trigger=trigger, product_id=product_id,
                event_type=event_type, event_id=event_id, input_payload=input_payload,
                dry_run=dry_run, llm_mode=llm_mode,
            ))
        return decision_id, True
    except IntegrityError:
        existing = find_by_event_id(event_id) if event_id else None
        if existing is None:
            raise
        return existing["decision_id"], False


def finish_record(decision_id: str, status: str, **fields) -> None:
    """Move a RECEIVED record to its post-graph status and store the results."""
    _transition(decision_id, status, **fields)


def get_record(decision_id: str) -> dict:
    with db_service.get_session() as session:
        record = session.get(DecisionRecord, decision_id)
        if record is None:
            raise DecisionNotFound(decision_id)
        return to_dict(record)


def find_by_event_id(event_id: str) -> dict | None:
    with db_service.get_session() as session:
        record = session.query(DecisionRecord).filter_by(event_id=event_id).first()
        return to_dict(record) if record else None


def list_records(limit: int = 50, status: str | None = None) -> list[dict]:
    with db_service.get_session() as session:
        query = session.query(DecisionRecord)
        if status:
            query = query.filter(DecisionRecord.status == status)
        rows = query.order_by(DecisionRecord.created_at.desc()).limit(limit).all()
        return [to_dict(r) for r in rows]


def _transition(decision_id: str, target: str, session=None, **fields) -> None:
    """
    Compare-and-set status change. Raises InvalidTransition if the record
    is not currently in a state that may move to `target`.
    """
    sources = _allowed_sources(target)

    def _do(s):
        updated = (s.query(DecisionRecord)
                   .filter(DecisionRecord.id == decision_id, DecisionRecord.status.in_(sources))
                   .update({"status": target, "updated_at": utcnow(), **fields},
                           synchronize_session=False))
        if updated != 1:
            current = s.get(DecisionRecord, decision_id)
            if current is None:
                raise DecisionNotFound(decision_id)
            raise InvalidTransition(decision_id, current.status, target)

    if session is not None:
        _do(session)
    else:
        with db_service.get_session() as s:
            _do(s)
    log.info("decision_transition", extra={"fields": {"decision_id": decision_id, "to": target}})


# --- Human review -----------------------------------------------------------

def approve(decision_id: str, reviewer: str, note: str | None = None) -> dict:
    """PENDING_APPROVAL -> APPROVED, then execute. Returns the updated record."""
    _transition(decision_id, APPROVED, reviewed_by=reviewer, review_note=note, reviewed_at=utcnow())
    return execute(decision_id)


def reject(decision_id: str, reviewer: str, note: str | None = None) -> dict:
    """PENDING_APPROVAL -> REJECTED. A rejected decision can never execute."""
    _transition(decision_id, REJECTED, reviewed_by=reviewer, review_note=note, reviewed_at=utcnow())
    return get_record(decision_id)


def retry_execution(decision_id: str) -> dict:
    """Only valid from EXECUTION_FAILED; same idempotency guarantees as execute()."""
    record = get_record(decision_id)
    if record["status"] != EXECUTION_FAILED:
        raise InvalidTransition(decision_id, record["status"], "EXECUTING (retry)")
    return execute(decision_id)


# --- Execution ----------------------------------------------------------------

def execute(decision_id: str) -> dict:
    """
    Perform the approved action. Allowed only from APPROVED, AUTO_APPROVED
    or EXECUTION_FAILED (retry).

    Step 1 claims the decision (-> EXECUTING) in its own transaction, so a
    concurrent call fails with InvalidTransition instead of executing twice.
    Step 2 writes the PO and marks EXECUTED in one transaction. If step 2
    fails, it is rolled back (no PO) and the record becomes EXECUTION_FAILED
    with the error, ready for a retry.
    """
    _transition(decision_id, EXECUTING)
    record = get_record(decision_id)
    decision = record["final_decision"] or {}
    details = decision.get("details") or {}

    try:
        with db_service.get_session() as session:
            if decision.get("decision_type") != "REORDER" or not details.get("supplier_id") \
                    or (details.get("quantity") or 0) <= 0:
                raise ValueError(f"not an executable REORDER: {decision.get('decision_type')}, "
                                 f"supplier={details.get('supplier_id')}, qty={details.get('quantity')}")

            if record["dry_run"]:
                result = {
                    "mode": "dry_run",
                    "action": "NO_WRITE",
                    "message": (f"Dry run: would create a purchase order for {details['quantity']} units "
                                f"from supplier {details['supplier_id']} (expedite={details.get('expedite')})."),
                    "would_create": {"supplier_id": details["supplier_id"], "product_id": record["product_id"],
                                     "quantity": details["quantity"], "expedite": details.get("expedite")},
                }
            else:
                po_id = db_service.add_purchase_order(session, details["supplier_id"],
                                                      record["product_id"], details["quantity"])
                log_id = db_service.add_decision_log(
                    session, "coordinator",
                    f"REORDER: {details['quantity']} units from supplier {details['supplier_id']}, "
                    f"expedite={details.get('expedite')} [decision {decision_id}]",
                    decision.get("explanation", ""))
                result = {
                    "mode": "local_db",
                    "action": "PURCHASE_ORDER_CREATED",
                    "po_id": po_id,
                    "log_id": log_id,
                    "message": (f"Simulated procurement: purchase order #{po_id} written to the local "
                                f"database. No external system was contacted."),
                }
            _transition(decision_id, EXECUTED, session=session,
                        execution_result=result, executed_at=utcnow())
    except Exception as exc:
        log.warning("execution_failed", extra={"fields": {"decision_id": decision_id, "error": type(exc).__name__}})
        _transition(decision_id, EXECUTION_FAILED,
                    execution_result={"mode": "local_db", "action": "NONE", "message": "Execution failed; nothing was written."},
                    error={"stage": "execution", "type": type(exc).__name__, "message": str(exc)[:300]})
    return get_record(decision_id)
