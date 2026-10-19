"""
Snapshot overlays: "what the world looks like if X happened".

An overlay is a small set of changes applied to the database snapshot
*in memory* before the agents run. Events and simulator scenarios are
both expressed as overlays, so they go through exactly the same graph,
validation and governance as a normal cycle. The database is never
changed by an overlay.

Modelling note on demand: the data model has no demand history, only a
reorder point. Reorder point = expected demand over the lead time plus
safety stock, so it scales roughly linearly with demand. A demand spike
of factor m is therefore modelled as an effective reorder point of
ceil(reorder_point * m). This is a stated assumption, not a forecast.
"""

import copy
import math
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field


class SnapshotOverlay(BaseModel):
    """
    Schema-level checks only (types, sane ranges for simulation knobs).
    Values such as a negative inventory quantity are allowed through on
    purpose: they are *business-rule* violations, and the validation node
    must catch them before any agent runs. That is what the data-quality
    scenarios exercise.
    """
    model_config = ConfigDict(extra="forbid")

    inventory_quantity: int | None = Field(None, description="Replace on-hand stock")
    reorder_point: int | None = Field(None, description="Replace the reorder point")
    demand_multiplier: float | None = Field(None, gt=0, le=10, description="Scale the reorder point by expected demand change")
    shipment_delay_days: int | None = Field(None, ge=0, le=365, description="Push expected arrival back by N days")
    delayed_shipment_id: int | None = Field(None, description="Only delay this shipment (default: all shipments of the product)")
    supplier_reliability: dict[int, float] | None = Field(None, description="supplier_id -> reliability score")
    supplier_lead_time_days: dict[int, int] | None = Field(None, description="supplier_id -> lead time in days")
    clear_purchase_orders: bool = Field(False, description="Pretend there are no open POs or shipments")
    remove_inventory_record: bool = Field(False, description="Simulate a missing inventory row")

    def is_empty(self) -> bool:
        return not self.model_dump(exclude_defaults=True)


def apply_overlay(snapshot: dict, overlay: SnapshotOverlay | dict | None) -> dict:
    """
    Return a new snapshot with the overlay applied.

    The result carries:
      overlay_changes   human-readable list of what was changed
      overlay_errors    references the overlay made that do not exist
                        (validation turns these into blocking errors)
    """
    result = copy.deepcopy(snapshot)
    result.setdefault('overlay_changes', [])
    result.setdefault('overlay_errors', [])
    if overlay is None:
        return result
    if isinstance(overlay, dict):
        overlay = SnapshotOverlay(**overlay)

    changes = result['overlay_changes']
    errors = result['overlay_errors']
    inventory = result.get('inventory')

    if overlay.remove_inventory_record:
        result['inventory'] = None
        result['inventory_record_count'] = 0
        inventory = None
        changes.append("inventory record removed")

    if inventory is not None:
        if overlay.inventory_quantity is not None:
            changes.append(f"inventory quantity {inventory['quantity']} -> {overlay.inventory_quantity}")
            inventory['quantity'] = overlay.inventory_quantity
        if overlay.reorder_point is not None:
            changes.append(f"reorder point {inventory['reorder_point']} -> {overlay.reorder_point}")
            inventory['reorder_point'] = overlay.reorder_point
        if overlay.demand_multiplier is not None:
            base = inventory['reorder_point']
            effective = math.ceil(base * overlay.demand_multiplier)
            inventory['base_reorder_point'] = base
            inventory['demand_multiplier'] = overlay.demand_multiplier
            inventory['reorder_point'] = effective
            changes.append(f"demand x{overlay.demand_multiplier}: effective reorder point {base} -> {effective}")
    elif overlay.inventory_quantity is not None or overlay.reorder_point is not None or overlay.demand_multiplier:
        errors.append("overlay changes inventory but the product has no inventory record")

    if overlay.clear_purchase_orders:
        result['purchase_orders'] = []
        result['shipments'] = []
        changes.append("open purchase orders and shipments removed")

    if overlay.shipment_delay_days:
        targets = [
            sh for sh in result.get('shipments', [])
            if overlay.delayed_shipment_id is None or sh['id'] == overlay.delayed_shipment_id
        ]
        if overlay.delayed_shipment_id is not None and not targets:
            errors.append(f"shipment {overlay.delayed_shipment_id} is not an active shipment of this product")
        for sh in targets:
            if sh.get('expected_arrival'):
                eta = datetime.fromisoformat(sh['expected_arrival'])
                sh['expected_arrival'] = (eta + timedelta(days=overlay.shipment_delay_days)).isoformat()
                changes.append(f"shipment #{sh['id']} delayed by {overlay.shipment_delay_days} days")

    suppliers_by_id = {s['id']: s for s in result.get('suppliers', [])}
    for supplier_id, score in (overlay.supplier_reliability or {}).items():
        if supplier_id not in suppliers_by_id:
            errors.append(f"supplier {supplier_id} does not exist")
            continue
        changes.append(f"supplier {supplier_id} reliability {suppliers_by_id[supplier_id]['reliability_score']} -> {score}")
        suppliers_by_id[supplier_id]['reliability_score'] = score
    for supplier_id, days in (overlay.supplier_lead_time_days or {}).items():
        if supplier_id not in suppliers_by_id:
            errors.append(f"supplier {supplier_id} does not exist")
            continue
        changes.append(f"supplier {supplier_id} lead time {suppliers_by_id[supplier_id]['lead_time_days']} -> {days} days")
        suppliers_by_id[supplier_id]['lead_time_days'] = days

    return result
