"""
Preset what-if scenarios for the Streamlit simulator.

Each preset is just a product id and a SnapshotOverlay. Running one goes
through the real graph, validation and governance (as a dry run), so the
outcome shown in the UI is what the system actually decided, not a
canned screen. Expected outcomes below assume the seed data and default
thresholds in config.py.
"""

SCENARIOS = [
    {
        "key": "baseline",
        "name": "Baseline (no changes)",
        "description": "Current database state, nothing modified.",
        "product_id": 1,
        "overlay": {},
    },
    {
        "key": "low_inventory",
        "name": "Low inventory",
        "description": "Widget A stock drops from 250 to 60, below its reorder point of 100.",
        "product_id": 1,
        "overlay": {"inventory_quantity": 60},
    },
    {
        "key": "demand_spike",
        "name": "Sudden demand increase",
        "description": "Demand for Widget A triples, so its effective reorder point rises from 100 to 300.",
        "product_id": 1,
        "overlay": {"demand_multiplier": 3.0},
    },
    {
        "key": "supplier_delay",
        "name": "Supplier delay",
        "description": "Widget A's inbound shipment slips by 10 days and Reliable Corp's reliability falls to 80%.",
        "product_id": 1,
        "overlay": {"shipment_delay_days": 10, "supplier_reliability": {1: 0.80}},
    },
    {
        "key": "conflicting_signals",
        "name": "Conflicting signals",
        "description": ("Widget A has enough stock (120 vs reorder point 100) but no open orders or shipments: "
                        "demand and logistics agents flag HIGH risk while the inventory agent says HOLD."),
        "product_id": 1,
        "overlay": {"inventory_quantity": 120, "clear_purchase_orders": True},
    },
    {
        "key": "data_quality_failure",
        "name": "Data-quality failure",
        "description": "The warehouse feed reports -15 units for Widget B. Validation must stop the cycle.",
        "product_id": 2,
        "overlay": {"inventory_quantity": -15},
    },
    {
        "key": "order_ceiling",
        "name": "Demand surge beyond the order ceiling",
        "description": "Demand for Widget C rises 8x; the computed order exceeds the 1000-unit ceiling and is capped.",
        "product_id": 3,
        "overlay": {"demand_multiplier": 8.0},
    },
]

BY_KEY = {s["key"]: s for s in SCENARIOS}
