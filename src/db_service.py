from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from models import Product, Inventory, Supplier, PurchaseOrder, Shipment, DecisionLog
from datetime import datetime
import os


# Initialize engine and session factory
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/supply_chain.db')
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


@contextmanager
def get_session():
    """Context manager for database sessions"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# READ FUNCTIONS (for agents)

def read_supply_chain_snapshot():
    """
    Read complete supply chain state.
    Returns a dictionary with all relevant data.
    Used by agents for decision-making.
    """
    with get_session() as session:
        # Read product
        product = session.query(Product).first()
        
        # Read inventory
        inventory = session.query(Inventory).filter_by(product_id=product.id).first()
        
        # Read suppliers
        suppliers = session.query(Supplier).all()
        
        # Read active purchase orders
        purchase_orders = session.query(PurchaseOrder).filter(
            PurchaseOrder.status.in_(['pending', 'confirmed'])
        ).all()
        
        # Read active shipments
        shipments = session.query(Shipment).filter_by(status='in_transit').all()
        
        # Build snapshot dictionary
        snapshot = {
            'product': {
                'id': product.id,
                'name': product.name,
                'sku': product.sku
            },
            'inventory': {
                'quantity': inventory.quantity,
                'reorder_point': inventory.reorder_point
            },
            'suppliers': [
                {
                    'id': s.id,
                    'name': s.name,
                    'lead_time_days': s.lead_time_days,
                    'reliability_score': s.reliability_score
                }
                for s in suppliers
            ],
            'purchase_orders': [
                {
                    'id': po.id,
                    'supplier_id': po.supplier_id,
                    'quantity': po.quantity,
                    'status': po.status,
                    'created_at': po.created_at.isoformat()
                }
                for po in purchase_orders
            ],
            'shipments': [
                {
                    'id': sh.id,
                    'po_id': sh.po_id,
                    'status': sh.status,
                    'expected_arrival': sh.expected_arrival.isoformat() if sh.expected_arrival else None
                }
                for sh in shipments
            ]
        }
        
        return snapshot

def read_supply_chain_snapshot(product_id=None):
    """
    Read complete supply chain state.
    
    Args:
        product_id: Optional. If provided, filters data for specific product.
                    If None, returns data for first product (default behavior).
    
    Returns dictionary with all relevant data.
    """
    with get_session() as session:
        # Get product
        if product_id:
            product = session.query(Product).filter_by(id=product_id).first()
        else:
            product = session.query(Product).first()
        
        if not product:
            raise ValueError(f"Product not found: {product_id}")
        
        # Read inventory for this product
        inventory = session.query(Inventory).filter_by(product_id=product.id).first()
        
        # Read all suppliers (not product-specific)
        suppliers = session.query(Supplier).all()
        
        # Read purchase orders for this product
        purchase_orders = session.query(PurchaseOrder).filter(
            PurchaseOrder.product_id == product.id,
            PurchaseOrder.status.in_(['pending', 'confirmed'])
        ).all()
        
        # Read shipments for this product's POs
        po_ids = [po.id for po in purchase_orders]
        if po_ids:
            shipments = session.query(Shipment).filter(
                Shipment.po_id.in_(po_ids),
                Shipment.status == 'in_transit'
            ).all()
        else:
            shipments = []
        
        # Build snapshot
        snapshot = {
            'product': {
                'id': product.id,
                'name': product.name,
                'sku': product.sku
            },
            'inventory': {
                'quantity': inventory.quantity,
                'reorder_point': inventory.reorder_point
            },
            'suppliers': [
                {
                    'id': s.id,
                    'name': s.name,
                    'lead_time_days': s.lead_time_days,
                    'reliability_score': s.reliability_score
                }
                for s in suppliers
            ],
            'purchase_orders': [
                {
                    'id': po.id,
                    'supplier_id': po.supplier_id,
                    'quantity': po.quantity,
                    'status': po.status,
                    'created_at': po.created_at.isoformat()
                }
                for po in purchase_orders
            ],
            'shipments': [
                {
                    'id': sh.id,
                    'po_id': sh.po_id,
                    'status': sh.status,
                    'expected_arrival': sh.expected_arrival.isoformat() if sh.expected_arrival else None
                }
                for sh in shipments
            ]
        }
        
        return snapshot


# WRITE FUNCTIONS (for execution nodes only)

def create_purchase_order(supplier_id, product_id, quantity):
    """
    Create a new purchase order.
    Only called from execution nodes, never from agents.
    """
    with get_session() as session:
        po = PurchaseOrder(
            supplier_id=supplier_id,
            product_id=product_id,
            quantity=quantity,
            status='pending',
            created_at=datetime.utcnow()
        )
        session.add(po)
        session.flush()
        po_id = po.id
        
    return po_id


def log_decision(agent_name, decision, reasoning):
    """
    Log an agent's decision with reasoning.
    Only called from execution nodes, never from agents.
    """
    with get_session() as session:
        log_entry = DecisionLog(
            agent_name=agent_name,
            decision=decision,
            reasoning=reasoning,
            timestamp=datetime.utcnow()
        )
        session.add(log_entry)
        session.flush()
        log_id = log_entry.id
        
    return log_id

