"""Layer 1: event schema validation, event rules and trigger thresholds."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from conftest import make_snapshot
from events import check_event_rules, evaluate_trigger, parse_event, to_overlay


def _event(**overrides):
    payload = {"event_id": "e-1", "event_type": "INVENTORY_LEVEL_CHANGED", "product_id": 1,
               "observed_quantity": 40, "occurred_at": datetime.now(timezone.utc).isoformat()}
    payload.update(overrides)
    return payload


def test_valid_event_is_parsed_into_its_model():
    event = parse_event(_event())
    assert type(event).__name__ == "InventoryLevelChanged"
    assert event.occurred_at.tzinfo is None  # normalised to naive UTC


@pytest.mark.parametrize("field", ["event_id", "product_id", "occurred_at", "observed_quantity", "event_type"])
def test_missing_required_field_is_rejected(field):
    payload = _event()
    del payload[field]
    with pytest.raises(ValidationError):
        parse_event(payload)


@pytest.mark.parametrize("overrides", [
    {"observed_quantity": -5},             # negative stock
    {"observed_quantity": "lots"},         # wrong type
    {"product_id": 0},                     # invalid id
    {"event_type": "PRICE_CHANGED"},       # unknown event type
    {"event_id": "has spaces!"},           # unsafe id characters
    {"event_id": "x" * 65},                # too long
    {"unexpected": "field"},               # extra fields are forbidden
    {"occurred_at": "yesterday"},          # malformed timestamp
])
def test_malformed_values_are_rejected(overrides):
    with pytest.raises(ValidationError):
        parse_event(_event(**overrides))


def test_each_event_type_only_accepts_its_own_fields():
    # A DEMAND_SPIKE carrying an inventory field (and no multiplier) is invalid.
    with pytest.raises(ValidationError):
        parse_event(_event(event_type="DEMAND_SPIKE"))
    payload = _event(event_type="DEMAND_SPIKE", demand_multiplier=2.0)
    del payload["observed_quantity"]
    assert parse_event(payload).demand_multiplier == 2.0


def test_stale_and_future_events_break_event_rules():
    now = datetime.now(timezone.utc)
    stale = parse_event(_event(occurred_at=(now - timedelta(hours=48)).isoformat()))
    future = parse_event(_event(occurred_at=(now + timedelta(hours=2)).isoformat()))
    fresh = parse_event(_event())
    assert [e["code"] for e in check_event_rules(stale)] == ["STALE_EVENT"]
    assert [e["code"] for e in check_event_rules(future)] == ["FUTURE_EVENT"]
    assert check_event_rules(fresh) == []


def test_inventory_event_triggers_only_below_reorder_point():
    snapshot = make_snapshot()  # reorder point 100
    assert evaluate_trigger(parse_event(_event(observed_quantity=99)), snapshot)[0] is True
    assert evaluate_trigger(parse_event(_event(observed_quantity=100)), snapshot)[0] is False


def test_demand_and_delay_thresholds():
    base = {k: v for k, v in _event().items() if k != "observed_quantity"}
    small = parse_event({**base, "event_type": "DEMAND_SPIKE", "demand_multiplier": 1.1})
    big = parse_event({**base, "event_type": "DEMAND_SPIKE", "demand_multiplier": 1.5})
    short = parse_event({**base, "event_type": "SHIPMENT_DELAYED", "delay_days": 1})
    long = parse_event({**base, "event_type": "SHIPMENT_DELAYED", "delay_days": 3})
    snapshot = make_snapshot()
    assert [evaluate_trigger(e, snapshot)[0] for e in (small, big, short, long)] == [False, True, False, True]


def test_events_map_to_overlays():
    base = {k: v for k, v in _event().items() if k != "observed_quantity"}
    assert to_overlay(parse_event(_event(observed_quantity=7))).inventory_quantity == 7
    delayed = to_overlay(parse_event({**base, "event_type": "SHIPMENT_DELAYED", "delay_days": 4, "shipment_id": 2}))
    assert (delayed.shipment_delay_days, delayed.delayed_shipment_id) == (4, 2)
