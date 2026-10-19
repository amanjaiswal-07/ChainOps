"""
Business events that can start a decision cycle.

Each event type is a Pydantic model. The `event_type` field selects the
model (a discriminated union), so a payload is checked against exactly the
fields that event needs and nothing else (extra fields are rejected).

Lifecycle of an event:
  1. Schema validation (Pydantic)            -> HTTP 422 on failure
  2. Idempotency check on event_id           -> same decision returned on replay
  3. Event business rules (timestamp sanity) -> VALIDATION_FAILED record
  4. Trigger rule (is this worth a cycle?)   -> NOT_TRIGGERED record if not
  5. Event converted to a snapshot overlay and run through the graph
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

import config
from models import utcnow
from overlay import SnapshotOverlay


class EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$",
                          description="Unique id from the sender. Re-sending the same id is safe (idempotent).")
    product_id: int = Field(..., gt=0)
    occurred_at: datetime = Field(..., description="When the event happened (ISO 8601). Timezone-aware values are converted to UTC.")
    source: str = Field("webhook", max_length=64, description="Free-text origin, e.g. 'wms-webhook' or 'scanner'")

    @field_validator("occurred_at")
    @classmethod
    def _to_naive_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class InventoryLevelChanged(EventBase):
    """A warehouse system reports a new on-hand quantity."""
    event_type: Literal["INVENTORY_LEVEL_CHANGED"]
    observed_quantity: int = Field(..., ge=0, le=1_000_000)


class ShipmentDelayed(EventBase):
    """A carrier reports that a shipment will arrive late."""
    event_type: Literal["SHIPMENT_DELAYED"]
    shipment_id: int | None = Field(None, gt=0, description="Omit to delay every active shipment of the product")
    delay_days: int = Field(..., ge=1, le=365)


class DemandSpike(EventBase):
    """Sales/marketing signals that demand is about to change by a factor."""
    event_type: Literal["DEMAND_SPIKE"]
    demand_multiplier: float = Field(..., gt=0, le=10)


SupplyChainEvent = Annotated[
    Union[InventoryLevelChanged, ShipmentDelayed, DemandSpike],
    Field(discriminator="event_type"),
]
EVENT_TYPES = ["INVENTORY_LEVEL_CHANGED", "SHIPMENT_DELAYED", "DEMAND_SPIKE"]

_adapter = TypeAdapter(SupplyChainEvent)


def parse_event(payload: dict):
    """Validate a raw dict into the right event model (raises pydantic.ValidationError)."""
    return _adapter.validate_python(payload)


def check_event_rules(event, now: datetime | None = None) -> list[dict]:
    """Business rules about the event itself (not the data it refers to)."""
    now = now or utcnow()
    errors = []
    if now - event.occurred_at > timedelta(hours=config.EVENT_MAX_AGE_HOURS):
        errors.append({"code": "STALE_EVENT", "field": "occurred_at",
                       "message": f"event is older than {config.EVENT_MAX_AGE_HOURS}h; "
                                  "refusing to act on outdated information"})
    if event.occurred_at - now > timedelta(minutes=config.EVENT_FUTURE_SKEW_MINUTES):
        errors.append({"code": "FUTURE_EVENT", "field": "occurred_at",
                       "message": "event timestamp is in the future"})
    return errors


def evaluate_trigger(event, snapshot: dict) -> tuple[bool, str]:
    """
    Decide whether the event is significant enough to run the agents.
    `snapshot` is the unmodified DB snapshot for the event's product.
    """
    if isinstance(event, InventoryLevelChanged):
        inventory = snapshot.get('inventory')
        if inventory is None:
            # Let validation report the missing record instead of hiding it.
            return True, "no inventory record on file; running cycle so validation reports it"
        rop = inventory['reorder_point']
        if event.observed_quantity < rop:
            return True, f"observed stock {event.observed_quantity} is below reorder point {rop}"
        return False, f"observed stock {event.observed_quantity} is at or above reorder point {rop}"

    if isinstance(event, ShipmentDelayed):
        threshold = config.SHIPMENT_DELAY_THRESHOLD_DAYS
        if event.delay_days >= threshold:
            return True, f"delay of {event.delay_days} days meets the {threshold}-day threshold"
        return False, f"delay of {event.delay_days} days is under the {threshold}-day threshold"

    if isinstance(event, DemandSpike):
        threshold = config.DEMAND_SPIKE_THRESHOLD
        if event.demand_multiplier >= threshold:
            return True, f"demand x{event.demand_multiplier} meets the x{threshold} threshold"
        return False, f"demand x{event.demand_multiplier} is under the x{threshold} threshold"

    return False, "unsupported event type"


def to_overlay(event) -> SnapshotOverlay:
    """Translate an event into the snapshot change it implies."""
    if isinstance(event, InventoryLevelChanged):
        return SnapshotOverlay(inventory_quantity=event.observed_quantity)
    if isinstance(event, ShipmentDelayed):
        return SnapshotOverlay(shipment_delay_days=event.delay_days, delayed_shipment_id=event.shipment_id)
    if isinstance(event, DemandSpike):
        return SnapshotOverlay(demand_multiplier=event.demand_multiplier)
    return SnapshotOverlay()
