"""
Create the schema and seed the demo data.

The seed defines three products with deliberately different risk profiles
so that one run of the workflow shows a HOLD, a HIGH-risk reorder with no
open PO, and a HIGH-risk reorder with a late shipment.
"""

from datetime import timedelta

from sqlalchemy.orm import sessionmaker

import db_service
from models import Base, Product, Inventory, Supplier, PurchaseOrder, Shipment, utcnow


def init_database():
    """Create all tables on the configured database (see config.DATABASE_URL)."""
    engine = db_service.engine
    Base.metadata.create_all(engine)
    return engine


def seed_data(engine):
    """
    Seed database with controlled multi-product scenarios.
    
    3 products, 3 suppliers, 1 warehouse, 2 risk profiles.
    NO schema changes.
    """
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        if session.query(Product).count() > 0:
            print("Database already seeded")
            return
        
        # 3 PRODUCTS
        products = [
            Product(id=1, name='Widget A - Standard', sku='WGT-A-001'),
            Product(id=2, name='Widget B - Premium', sku='WGT-B-002'),
            Product(id=3, name='Widget C - Specialized', sku='WGT-C-003')
        ]
        session.add_all(products)
        
        # 3 SUPPLIERS
        suppliers = [
            Supplier(id=1, name='Reliable Corp', lead_time_days=5, reliability_score=0.95),
            Supplier(id=2, name='Fast Shipping Inc', lead_time_days=2, reliability_score=0.85),
            Supplier(id=3, name='Budget Supplies', lead_time_days=10, reliability_score=0.75)
        ]
        session.add_all(suppliers)
        
        # INVENTORY (1 warehouse, 3 products)
        # Product A: STABLE - comfortable stock
        # Product B: VOLATILE - below reorder point
        # Product C: HIGH RISK - critically low
        inventories = [
            Inventory(id=1, product_id=1, quantity=250, reorder_point=100),
            Inventory(id=2, product_id=2, quantity=50, reorder_point=100),
            Inventory(id=3, product_id=3, quantity=20, reorder_point=80)
        ]
        session.add_all(inventories)
        
        # PURCHASE ORDERS
        # Product A: Active order with reliable supplier
        # Product B: No order (triggers HIGH risk)
        # Product C: Order with risky supplier
        purchase_orders = [
            PurchaseOrder(
                id=1,
                supplier_id=1,
                product_id=1,
                quantity=150,
                status='confirmed',
                created_at=utcnow() - timedelta(days=2)
            ),
            PurchaseOrder(
                id=2,
                supplier_id=3,
                product_id=3,
                quantity=100,
                status='confirmed',
                created_at=utcnow() - timedelta(days=5)
            )
        ]
        session.add_all(purchase_orders)
        
        # SHIPMENTS
        # Product A: Arriving soon (LOW RISK)
        # Product C: Delayed (HIGH RISK)
        shipments = [
            Shipment(
                id=1,
                po_id=1,
                status='in_transit',
                expected_arrival=utcnow() + timedelta(days=3)
            ),
            Shipment(
                id=2,
                po_id=2,
                status='in_transit',
                expected_arrival=utcnow() + timedelta(days=12)
            )
        ]
        session.add_all(shipments)
        
        session.commit()
        
        print("="*70)
        print("Database seeded successfully")
        print("="*70)
        print("\nProduct A (Stable): 250 units, PO arriving in 3 days -> LOW risk")
        print("Product B (Volatile): 50 units, no PO -> HIGH risk")
        print("Product C (High Risk): 20 units, delayed shipment -> HIGH risk")
        print("="*70)
        
    except Exception as e:
        session.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        session.close()


def ensure_database():
    """Create tables and seed demo data if the database is empty. Idempotent."""
    engine = init_database()
    with db_service.get_session() as session:
        if session.query(Product).count() == 0:
            seed_data(engine)
    return engine


if __name__ == '__main__':
    engine = init_database()
    seed_data(engine)
    print(f"\nDatabase initialized at {engine.url}")
