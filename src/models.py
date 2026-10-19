from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime


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
    created_at = Column(DateTime, default=datetime.utcnow)


class Shipment(Base):
    __tablename__ = 'shipments'
    
    id = Column(Integer, primary_key=True)
    po_id = Column(Integer, ForeignKey('purchase_orders.id'), nullable=False)
    status = Column(String, default='in_transit')
    expected_arrival = Column(DateTime)
    actual_arrival = Column(DateTime, nullable=True)


class DecisionLog(Base):
    __tablename__ = 'decision_log'
    
    id = Column(Integer, primary_key=True)
    agent_name = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    reasoning = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

class ApprovalQueue(Base):
    __tablename__ = 'approval_queue'
    id = Column(Integer, primary_key=True)
    decision_log_id = Column(Integer)
    status = Column(String, default='pending')
    decision_data = Column(String)
    requested_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reviewer_email = Column(String, nullable=True)
    feedback = Column(String, nullable=True)
