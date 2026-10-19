"""HTTP API behaviour through FastAPI's TestClient (no server process needed)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture
def client():
    # raise_server_exceptions=False lets us see the generic 500 body
    with TestClient(api.app, raise_server_exceptions=False) as c:
        yield c


def event(**overrides):
    payload = {"event_id": "api-1", "event_type": "INVENTORY_LEVEL_CHANGED", "product_id": 2,
               "observed_quantity": 30, "occurred_at": datetime.now(timezone.utc).isoformat(), "source": "test"}
    payload.update(overrides)
    return payload


def test_health(client):
    body = client.get("/health").json()
    assert body == {"status": "ok", "llm_mode": "offline", "products": 3}


def test_post_event_runs_cycle_and_returns_summary(client):
    r = client.post("/events", json=event())
    assert r.status_code == 201
    body = r.json()
    assert body["decision_id"].startswith("dec_")
    assert body["event_type"] == "INVENTORY_LEVEL_CHANGED"
    assert body["status"] == "PENDING_APPROVAL"
    assert body["risk_level"] == "HIGH"
    assert body["approval_required"] is True
    assert body["recommended_action"] == {"decision_type": "REORDER", "supplier_id": 1, "quantity": 170, "expedite": True}
    assert set(body["links"]) == {"self", "approve", "reject"}


def test_duplicate_event_returns_200_and_same_decision(client):
    first = client.post("/events", json=event()).json()
    r = client.post("/events", json=event())
    assert r.status_code == 200
    assert r.json()["decision_id"] == first["decision_id"] and r.json()["duplicate"] is True


@pytest.mark.parametrize("bad", [
    {"observed_quantity": -1}, {"observed_quantity": "ten"}, {"event_type": "UNKNOWN"}, {"surprise": 1},
])
def test_schema_errors_are_422(client, bad):
    assert client.post("/events", json=event(**bad)).status_code == 422


def test_missing_field_is_422(client):
    payload = event()
    del payload["occurred_at"]
    r = client.post("/events", json=payload)
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "occurred_at"


def test_business_rule_failure_is_a_recorded_decision(client):
    r = client.post("/events", json=event(product_id=999))
    assert r.status_code == 201 and r.json()["status"] == "VALIDATION_FAILED"


def test_oversized_payload_is_413(client):
    r = client.post("/events", content=b"{" + b" " * 20_000 + b"}", headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_approve_and_reject_enforce_transitions(client):
    did = client.post("/decision-cycles", json={"product_id": 2}).json()["decision_id"]
    approved = client.post(f"/decisions/{did}/approve", json={"reviewer": "alice"})
    assert approved.status_code == 200 and approved.json()["status"] == "EXECUTED"
    again = client.post(f"/decisions/{did}/reject", json={"reviewer": "bob"})
    assert again.status_code == 409
    assert again.json() == {"error": "invalid_transition", "decision_id": did, "current_status": "EXECUTED",
                            "attempted": "REJECTED", "message": f"decision {did} is EXECUTED; cannot move to REJECTED"}


def test_reject_flow(client):
    did = client.post("/decision-cycles", json={"product_id": 3}).json()["decision_id"]
    assert client.post(f"/decisions/{did}/reject", json={"reviewer": "bob", "note": "no"}).json()["status"] == "REJECTED"
    assert client.post(f"/decisions/{did}/approve", json={"reviewer": "bob"}).status_code == 409
    full = client.get(f"/decisions/{did}").json()
    assert full["reviewed_by"] == "bob" and full["review_note"] == "no" and full["execution_result"] is None


def test_review_requires_reviewer(client):
    did = client.post("/decision-cycles", json={"product_id": 2}).json()["decision_id"]
    assert client.post(f"/decisions/{did}/approve", json={}).status_code == 422
    assert client.post(f"/decisions/{did}/approve", json={"reviewer": ""}).status_code == 422


def test_hold_cannot_be_approved(client):
    did = client.post("/decision-cycles", json={"product_id": 1}).json()["decision_id"]
    assert client.post(f"/decisions/{did}/approve", json={"reviewer": "alice"}).status_code == 409


def test_scenario_cycle_is_forced_dry_run(client):
    body = client.post("/decision-cycles", json={"product_id": 1, "overlay": {"inventory_quantity": 60}}).json()
    assert body["trigger"] == "SCENARIO"
    executed = client.post(f"/decisions/{body['decision_id']}/approve", json={"reviewer": "alice"}).json()
    assert executed["execution_result"]["mode"] == "dry_run"


def test_unknown_product_and_decision_are_404(client):
    assert client.post("/decision-cycles", json={"product_id": 99}).status_code == 404
    assert client.get("/decisions/dec_nope").status_code == 404
    assert client.post("/decisions/dec_nope/approve", json={"reviewer": "a"}).status_code == 404


def test_retry_only_from_execution_failed(client):
    did = client.post("/decision-cycles", json={"product_id": 2}).json()["decision_id"]
    assert client.post(f"/decisions/{did}/retry-execution").status_code == 409


def test_list_decisions_with_filter(client):
    client.post("/decision-cycles", json={"product_id": 1})
    client.post("/decision-cycles", json={"product_id": 2})
    pending = client.get("/decisions", params={"status": "PENDING_APPROVAL"}).json()
    assert [d["product_id"] for d in pending] == [2]


def test_unexpected_errors_do_not_leak_details(client, monkeypatch):
    import workflow

    def explode(*args, **kwargs):
        raise RuntimeError("secret connection string sqlite:///C:/private")
    monkeypatch.setattr(workflow, "run_cycle", explode)
    r = client.post("/decision-cycles", json={"product_id": 1})
    assert r.status_code == 500
    assert set(r.json()) == {"error", "error_id"} and "secret" not in r.text


def test_live_mode_without_key_gives_clear_503(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "LLM_MODE", "live")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = client.post("/decision-cycles", json={"product_id": 1})
    assert r.status_code == 503 and "OPENROUTER_API_KEY" in r.json()["message"]
