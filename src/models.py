"""
SQLAlchemy models for the supply chain database.

The first five tables are the operational data the agents read. DecisionLog
is the original free-text log and is kept for compatibility. DecisionRecord
is the audit trail added for ChainOps: one row per decision cycle, holding
everything needed to understand why a decision was made and what happened
to it afterwards.

All timestamps are naive UTC, matching the data the original project seeded.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Current time as naive UTC (datetime.utcnow() is deprecated)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


class Product(Base):
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sku = Column(String, unique=True, nullable=False)


class Inventory(Base):
    __tablename__ = 'inventory'

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = Column(Integer, default=0)
    reorder_point = Column(Integer, default=100)


class Supplier(Base):
    __tablename__ = 'suppliers'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    lead_time_days = Column(Integer, nullable=False)
    reliability_score = Column(Float, default=1.0)


class PurchaseOrder(Base):
    __tablename__ = 'purchase_orders'

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=utcnow)


class Shipment(Base):
    __tablename__ = 'shipments'

    id = Column(Integer, primary_key=True)
    po_id = Column(Integer, ForeignKey('purchase_orders.id'), nullable=False)
    status = Column(String, default='in_transit')
    expected_arrival = Column(DateTime)
    actual_arrival = Column(DateTime, nullable=True)


class DecisionLog(Base):
    """Original free-text decision log (kept; execution still appends to it)."""
    __tablename__ = 'decision_log'

    id = Column(Integer, primary_key=True)
    agent_name = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    reasoning = Column(String)
    timestamp = Column(DateTime, default=utcnow)


class DecisionRecord(Base):
    """
    Audit record for one decision cycle.

    `status` follows the state machine in governance.py. Only governance.py
    changes it after creation, and it does so with compare-and-set updates
    so two concurrent approvals cannot both execute.
    """
    __tablename__ = 'decision_records'

    id = Column(String, primary_key=True)                # e.g. "dec_3f9a1c2b7e4d"
    status = Column(String, nullable=False, index=True)

    # What started the cycle
    trigger = Column(String, nullable=False)             # MANUAL | EVENT | SCENARIO
    event_type = Column(String, nullable=True)
    event_id = Column(String, nullable=True, unique=True)  # idempotency key for events
    product_id = Column(Integer, nullable=True)
    input_payload = Column(JSON, nullable=True)          # event payload or scenario overlay
    dry_run = Column(Boolean, default=False)             # True: never writes a PO

    # What the system saw and concluded
    validation_status = Column(String, nullable=True)    # PASSED | PASSED_WITH_WARNINGS | FAILED
    validation_report = Column(JSON, nullable=True)
    snapshot = Column(JSON, nullable=True)               # data the agents actually used
    agent_trace = Column(JSON, nullable=True)            # ordered [{node, duration_ms}]
    agent_outputs = Column(JSON, nullable=True)
    final_decision = Column(JSON, nullable=True)
    risk_level = Column(String, nullable=True)
    risk_reasons = Column(JSON, nullable=True)
    approval_required = Column(Boolean, nullable=True)
    llm_mode = Column(String, nullable=True)

    # What happened to the recommendation
    reviewed_by = Column(String, nullable=True)
    review_note = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    execution_result = Column(JSON, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    error = Column(JSON, nullable=True)

    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
