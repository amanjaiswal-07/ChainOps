"""Layer 2: business-rule validation of snapshots, and overlays."""

from datetime import datetime, timedelta

import pytest

from conftest import make_snapshot
from overlay import SnapshotOverlay, apply_overlay
from validation import FAILED, PASSED, PASSED_WITH_WARNINGS, validate_snapshot


def codes(report, kind="errors"):
    return [issue["code"] for issue in report[kind]]


def test_valid_snapshot_passes():
    report = validate_snapshot(make_snapshot())
    assert report == {"status": PASSED, "errors": [], "warnings": []}


@pytest.mark.parametrize("changes, code", [
    ({"inventory": {"quantity": -1, "reorder_point": 100}}, "NEGATIVE_INVENTORY"),
    ({"inventory": {"quantity": "50", "reorder_point": 100}}, "MALFORMED_VALUE"),
    ({"inventory": {"quantity": 50, "reorder_point": 0}}, "INVALID_REORDER_POINT"),
    ({"inventory": {"quantity": None, "reorder_point": 100}}, "MISSING_FIELD"),
    ({"inventory": None, "inventory_record_count": 0}, "MISSING_INVENTORY"),
    ({"inventory_record_count": 2}, "DUPLICATE_RECORD"),
    ({"suppliers": []}, "NO_SUPPLIERS"),
    ({"suppliers": [{"id": 1, "name": "X", "lead_time_days": 5, "reliability_score": 1.4}]}, "OUT_OF_RANGE"),
    ({"suppliers": [{"id": 1, "name": "X", "lead_time_days": 0, "reliability_score": 0.9}]}, "OUT_OF_RANGE"),
    ({"product": {"id": 2, "sku": ""}}, "MISSING_FIELD"),
])
def test_business_rule_violations_are_errors(changes, code):
    report = validate_snapshot(make_snapshot(**changes))
    assert report["status"] == FAILED
    assert code in codes(report)


def test_purchase_order_rules():
    now = datetime(2026, 1, 1)
    bad_supplier = {"id": 7, "supplier_id": 99, "quantity": 10, "status": "pending", "created_at": now.isoformat()}
    bad_qty = {"id": 8, "supplier_id": 1, "quantity": 0, "status": "pending", "created_at": now.isoformat()}
    report = validate_snapshot(make_snapshot(purchase_orders=[bad_supplier, bad_qty]), now=now)
    assert "INCONSISTENT_REFERENCE" in codes(report)
    assert "INVALID_QUANTITY" in codes(report)


def test_orphan_shipment_is_inconsistent():
    shipment = {"id": 5, "po_id": 42, "status": "in_transit", "expected_arrival": "2026-01-05T00:00:00"}
    report = validate_snapshot(make_snapshot(shipments=[shipment]))
    assert "INCONSISTENT_REFERENCE" in codes(report)


def test_stale_po_and_missing_eta_are_warnings_not_errors():
    now = datetime(2026, 3, 1)
    old_po = {"id": 1, "supplier_id": 1, "quantity": 10, "status": "pending",
              "created_at": (now - timedelta(days=60)).isoformat()}
    po_with_ship = {"id": 2, "supplier_id": 1, "quantity": 10, "status": "confirmed", "created_at": now.isoformat()}
    no_eta = {"id": 3, "po_id": 2, "status": "in_transit", "expected_arrival": None}
    report = validate_snapshot(make_snapshot(purchase_orders=[old_po, po_with_ship], shipments=[no_eta]), now=now)
    assert report["status"] == PASSED_WITH_WARNINGS
    assert sorted(codes(report, "warnings")) == ["MISSING_FIELD", "STALE_RECORD"]


def test_overlay_demand_multiplier_scales_reorder_point():
    snap = apply_overlay(make_snapshot(), SnapshotOverlay(demand_multiplier=1.5))
    assert snap["inventory"]["reorder_point"] == 150
    assert snap["inventory"]["base_reorder_point"] == 100


def test_overlay_shipment_delay_moves_eta():
    po = {"id": 2, "supplier_id": 1, "quantity": 10, "status": "confirmed", "created_at": "2026-01-01T00:00:00"}
    ship = {"id": 9, "po_id": 2, "status": "in_transit", "expected_arrival": "2026-01-10T00:00:00"}
    snap = apply_overlay(make_snapshot(purchase_orders=[po], shipments=[ship]), {"shipment_delay_days": 4})
    assert snap["shipments"][0]["expected_arrival"] == "2026-01-14T00:00:00"


def test_overlay_unknown_references_become_validation_errors():
    snap = apply_overlay(make_snapshot(), {"supplier_reliability": {99: 0.5}, "shipment_delay_days": 2,
                                           "delayed_shipment_id": 77})
    report = validate_snapshot(snap)
    assert report["status"] == FAILED
    assert codes(report).count("INCONSISTENT_REFERENCE") == 2


def test_overlay_does_not_mutate_the_original():
    original = make_snapshot()
    apply_overlay(original, {"inventory_quantity": -3})
    assert original["inventory"]["quantity"] == 50


def test_overlay_schema_rejects_unknown_fields():
    with pytest.raises(Exception):
        SnapshotOverlay(inventory_quantity=5, teleport=True)
