"""
Demonstrates automated, event-triggered decision cycles.

Two modes:

  webhook  Plays the part of external systems (WMS, carrier, sales) and
           POSTs a sequence of events to a running API. Shows triggering,
           thresholds, idempotent replays and both validation layers.

               uvicorn api:app --app-dir src --port 8000
               python scripts/event_simulator.py webhook --api http://localhost:8000

  scan     A scheduled monitor. Every --interval seconds it looks for
           products below their reorder point and raises an
           INVENTORY_LEVEL_CHANGED event for each. The event_id includes
           the product, quantity and hour, so re-scanning an unchanged
           situation is a duplicate and never opens a second decision.

               python scripts/event_simulator.py scan --once
               python scripts/event_simulator.py scan --interval 60
               python scripts/event_simulator.py scan --once --api http://localhost:8000
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _now(offset_hours: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=offset_hours)).isoformat()


def _show(label: str, response: httpx.Response):
    body = response.json()
    if response.status_code == 422:
        first = body["detail"][0]
        print(f"[{response.status_code}] {label}: rejected by schema: {'.'.join(map(str, first['loc']))}: {first['msg']}")
        return
    action = body.get("recommended_action") or {}
    print(f"[{response.status_code}] {label}: {body.get('decision_id')} status={body.get('status')} "
          f"risk={body.get('risk_level')} action={action.get('decision_type')} {action.get('quantity') or ''}"
          f"{' (duplicate)' if body.get('duplicate') else ''}")
    if body.get("trigger_reason"):
        print(f"      trigger: {body['trigger_reason']}")


def run_webhook(api: str):
    run = uuid.uuid4().hex[:6]
    low_stock = {"event_id": f"wms-{run}-1", "event_type": "INVENTORY_LEVEL_CHANGED", "product_id": 1,
                 "observed_quantity": 40, "occurred_at": _now(), "source": "wms-webhook"}
    events = [
        ("Stock for Widget A drops to 40", low_stock),
        ("Same webhook delivered again", low_stock),
        ("Stock report above reorder point", {**low_stock, "event_id": f"wms-{run}-2", "observed_quantity": 180}),
        ("Carrier: Widget C shipment 5 days late", {
            "event_id": f"carrier-{run}-1", "event_type": "SHIPMENT_DELAYED", "product_id": 3,
            "shipment_id": 2, "delay_days": 5, "occurred_at": _now(), "source": "carrier-webhook"}),
        ("Sales: demand +10% (under threshold)", {
            "event_id": f"sales-{run}-1", "event_type": "DEMAND_SPIKE", "product_id": 1,
            "demand_multiplier": 1.1, "occurred_at": _now(), "source": "sales-forecast"}),
        ("Sales: demand x3 for Widget A", {
            "event_id": f"sales-{run}-2", "event_type": "DEMAND_SPIKE", "product_id": 1,
            "demand_multiplier": 3.0, "occurred_at": _now(), "source": "sales-forecast"}),
        ("Negative stock in payload", {**low_stock, "event_id": f"wms-{run}-3", "observed_quantity": -5}),
        ("Event from two days ago", {**low_stock, "event_id": f"wms-{run}-4", "occurred_at": _now(-48)}),
        ("Shipment that belongs to another product", {
            "event_id": f"carrier-{run}-2", "event_type": "SHIPMENT_DELAYED", "product_id": 1,
            "shipment_id": 2, "delay_days": 4, "occurred_at": _now(), "source": "carrier-webhook"}),
    ]
    with httpx.Client(base_url=api, timeout=120) as client:
        print(f"API health: {json.dumps(client.get('/health').json())}\n")
        for label, payload in events:
            _show(label, client.post("/events", json=payload))


def scan_once(api: str | None):
    import db_init
    from db_service import find_products_below_reorder_point
    db_init.ensure_database()

    hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    found = find_products_below_reorder_point()
    print(f"{datetime.now().isoformat(timespec='seconds')} scan: {len(found)} product(s) below reorder point")
    for item in found:
        payload = {
            "event_id": f"scan-p{item['product_id']}-q{item['quantity']}-{hour}",
            "event_type": "INVENTORY_LEVEL_CHANGED",
            "product_id": item["product_id"],
            "observed_quantity": item["quantity"],
            "occurred_at": _now(),
            "source": "scheduled-scanner",
        }
        if api:
            _show(f"product {item['product_id']}", httpx.post(f"{api}/events", json=payload, timeout=120))
        else:
            from workflow import process_event
            record = process_event(payload)
            print(f"  product {item['product_id']}: {record['decision_id']} status={record['status']}"
                  f"{' (duplicate, already handled)' if record['duplicate'] else ''}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    w = sub.add_parser("webhook", help="POST sample events to a running API")
    w.add_argument("--api", default="http://localhost:8000")
    s = sub.add_parser("scan", help="scheduled monitor that raises low-stock events")
    s.add_argument("--api", default=None, help="send events over HTTP instead of in-process")
    s.add_argument("--interval", type=int, default=60, help="seconds between scans")
    s.add_argument("--once", action="store_true", help="scan once and exit")
    args = parser.parse_args()

    if args.mode == "webhook":
        run_webhook(args.api)
        return
    while True:
        scan_once(args.api)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
