"""
Business-rule validation of the data the agents are about to reason over.

ChainOps has three separate validation layers, each with its own job:

  1. Schema validation      events.py / overlay.py (Pydantic)
                            Is the payload well-formed? Wrong types, missing
                            fields and unknown fields are rejected with HTTP 422
                            before anything else happens.
  2. Business-rule checks   this module
                            Is the data *believable*? Negative stock, broken
                            references, duplicate rows, stale records.
  3. AI-output validation   agent_outputs.py
                            Did the LLM return something structurally valid
                            and consistent with the deterministic rules?

Results are split into:
  errors    the cycle stops before any agent runs (status VALIDATION_FAILED)
  warnings  data-quality concerns; agents run, but the decision gate forces
            human review for any actionable recommendation

Operational risks (late shipment, unreliable supplier) are NOT validation
problems: the data is fine, the situation is bad. Those are for the agents.
"""

from datetime import datetime, timedelta

import config
from models import utcnow

PASSED = "PASSED"
PASSED_WITH_WARNINGS = "PASSED_WITH_WARNINGS"
FAILED = "FAILED"


def _issue(code: str, field: str, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _is_int(value) -> bool:
    # bool is a subclass of int; a True/False quantity is malformed.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_ts(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return "invalid"


def validate_snapshot(snapshot: dict, now: datetime | None = None) -> dict:
    """
    Check a (possibly overlaid) snapshot. Returns
    {"status": PASSED|PASSED_WITH_WARNINGS|FAILED, "errors": [...], "warnings": [...]}.
    """
    now = now or utcnow()
    errors: list[dict] = []
    warnings: list[dict] = []

    # References an overlay or event tried to make that do not exist
    for message in snapshot.get('overlay_errors', []):
        errors.append(_issue("INCONSISTENT_REFERENCE", "input", message))

    # --- Product -----------------------------------------------------------
    product = snapshot.get('product') or {}
    if not product.get('id') or not product.get('sku'):
        errors.append(_issue("MISSING_FIELD", "product", "product id and sku are required"))

    # --- Inventory ---------------------------------------------------------
    inventory = snapshot.get('inventory')
    if inventory is None:
        errors.append(_issue("MISSING_INVENTORY", "inventory",
                             f"no inventory record for product {product.get('id')}"))
    else:
        qty = inventory.get('quantity')
        rop = inventory.get('reorder_point')
        if qty is None:
            errors.append(_issue("MISSING_FIELD", "inventory.quantity", "inventory quantity is missing"))
        elif not _is_int(qty):
            errors.append(_issue("MALFORMED_VALUE", "inventory.quantity", f"quantity must be an integer, got {qty!r}"))
        elif qty < 0:
            errors.append(_issue("NEGATIVE_INVENTORY", "inventory.quantity", f"inventory cannot be negative ({qty})"))

        if rop is None:
            errors.append(_issue("MISSING_FIELD", "inventory.reorder_point", "reorder point is missing"))
        elif not _is_int(rop):
            errors.append(_issue("MALFORMED_VALUE", "inventory.reorder_point", f"reorder point must be an integer, got {rop!r}"))
        elif rop <= 0:
            errors.append(_issue("INVALID_REORDER_POINT", "inventory.reorder_point",
                                 f"reorder point must be positive ({rop})"))

    if snapshot.get('inventory_record_count', 1) > 1:
        errors.append(_issue("DUPLICATE_RECORD", "inventory",
                             f"{snapshot['inventory_record_count']} inventory rows for one product; "
                             "stock level is ambiguous"))

    # --- Suppliers ---------------------------------------------------------
    suppliers = snapshot.get('suppliers') or []
    if not suppliers:
        errors.append(_issue("NO_SUPPLIERS", "suppliers", "no suppliers available to order from"))
    supplier_ids = [s.get('id') for s in suppliers]
    if len(supplier_ids) != len(set(supplier_ids)):
        errors.append(_issue("DUPLICATE_RECORD", "suppliers", "duplicate supplier ids"))
    for s in suppliers:
        label = f"suppliers[{s.get('id')}]"
        score = s.get('reliability_score')
        if not _is_number(score):
            errors.append(_issue("MALFORMED_VALUE", f"{label}.reliability_score", f"reliability must be a number, got {score!r}"))
        elif not 0.0 <= score <= 1.0:
            errors.append(_issue("OUT_OF_RANGE", f"{label}.reliability_score", f"reliability must be between 0 and 1 ({score})"))
        lead = s.get('lead_time_days')
        if not _is_int(lead):
            errors.append(_issue("MALFORMED_VALUE", f"{label}.lead_time_days", f"lead time must be an integer, got {lead!r}"))
        elif lead <= 0:
            errors.append(_issue("OUT_OF_RANGE", f"{label}.lead_time_days", f"lead time must be positive ({lead})"))

    # --- Purchase orders ---------------------------------------------------
    pos = snapshot.get('purchase_orders') or []
    po_ids = {po.get('id') for po in pos}
    shipment_po_ids = {sh.get('po_id') for sh in snapshot.get('shipments') or []}
    for po in pos:
        label = f"purchase_orders[{po.get('id')}]"
        if po.get('supplier_id') not in supplier_ids:
            errors.append(_issue("INCONSISTENT_REFERENCE", f"{label}.supplier_id",
                                 f"PO references unknown supplier {po.get('supplier_id')}"))
        if not _is_int(po.get('quantity')) or po['quantity'] <= 0:
            errors.append(_issue("INVALID_QUANTITY", f"{label}.quantity",
                                 f"PO quantity must be a positive integer ({po.get('quantity')!r})"))
        created = _parse_ts(po.get('created_at'))
        if created == "invalid":
            errors.append(_issue("MALFORMED_VALUE", f"{label}.created_at", "unparseable timestamp"))
        elif created and po.get('id') not in shipment_po_ids and now - created > timedelta(days=config.STALE_PO_DAYS):
            warnings.append(_issue("STALE_RECORD", label,
                                   f"PO open for {(now - created).days} days with no shipment in transit"))

    # --- Shipments ---------------------------------------------------------
    for sh in snapshot.get('shipments') or []:
        label = f"shipments[{sh.get('id')}]"
        if sh.get('po_id') not in po_ids:
            errors.append(_issue("INCONSISTENT_REFERENCE", f"{label}.po_id",
                                 f"shipment references PO {sh.get('po_id')} which is not open for this product"))
        eta = _parse_ts(sh.get('expected_arrival'))
        if eta == "invalid":
            errors.append(_issue("MALFORMED_VALUE", f"{label}.expected_arrival", "unparseable timestamp"))
        elif eta is None:
            warnings.append(_issue("MISSING_FIELD", f"{label}.expected_arrival",
                                   "in-transit shipment has no expected arrival date"))

    status = FAILED if errors else (PASSED_WITH_WARNINGS if warnings else PASSED)
    return {"status": status, "errors": errors, "warnings": warnings}
