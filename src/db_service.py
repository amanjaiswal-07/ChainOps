"""
Database access layer.

Agents never touch the database. They receive a read-only snapshot built
here. Writes happen only in governance.py (decision records, purchase
orders) through get_session(), which wraps each unit of work in a
transaction that commits on success and rolls back on any exception.

All queries use the SQLAlchemy ORM with bound parameters; there is no
string-built SQL anywhere in the project.
"""

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
from models import DecisionLog, Inventory, Product, PurchaseOrder, Shipment, Supplier, utcnow

engine = None
SessionLocal = None


def configure(database_url: str | None = None):
    """
    (Re)bind the module to a database. Called once at import with the
    configured URL; tests call it again to point at a temporary database.
    """
    global engine, SessionLocal
    url = database_url or config.DATABASE_URL
    if url.startswith("sqlite:///"):
        # Make sure the folder for a file-based SQLite DB exists.
        db_file = url.replace("sqlite:///", "", 1)
        if db_file and db_file != ":memory:":
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"timeout": 15, "check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, echo=False, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


configure()


@contextmanager
def get_session():
    """Context manager for one database transaction."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# READ FUNCTIONS (for agents and the validation layer)
# ---------------------------------------------------------------------------

def read_supply_chain_snapshot(product_id=None):
    """
    Read the supply chain state for one product.

    Args:
        product_id: Product to read. If None, the first product is used.

    Returns a plain dict. Missing or duplicated inventory rows are reported
    in the snapshot instead of crashing here, so the validation node can
    turn them into clear validation errors.

    Raises ValueError if the product does not exist.
    """
    with get_session() as session:
        if product_id is not None:
            product = session.get(Product, product_id)
        else:
            product = session.query(Product).first()

        if not product:
            raise ValueError(f"Product not found: {product_id}")

        inventory_rows = session.query(Inventory).filter_by(product_id=product.id).all()
        inventory = inventory_rows[0] if inventory_rows else None

        # Suppliers are shared across products in this data model.
        suppliers = session.query(Supplier).order_by(Supplier.id).all()

        purchase_orders = session.query(PurchaseOrder).filter(
            PurchaseOrder.product_id == product.id,
            PurchaseOrder.status.in_(['pending', 'confirmed'])
        ).order_by(PurchaseOrder.id).all()

        po_ids = [po.id for po in purchase_orders]
        shipments = session.query(Shipment).filter(
            Shipment.po_id.in_(po_ids),
            Shipment.status == 'in_transit'
        ).order_by(Shipment.id).all() if po_ids else []

        return {
            'product': {
                'id': product.id,
                'name': product.name,
                'sku': product.sku
            },
            'inventory': {
                'quantity': inventory.quantity,
                'reorder_point': inventory.reorder_point
            } if inventory else None,
            # Lets validation detect duplicate/inconsistent inventory rows.
            'inventory_record_count': len(inventory_rows),
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
                    'created_at': po.created_at.isoformat() if po.created_at else None
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
            ],
            'read_at': utcnow().isoformat(),
        }


def list_products():
    """All products as [{id, name, sku}], for the UI and API."""
    with get_session() as session:
        return [
            {'id': p.id, 'name': p.name, 'sku': p.sku}
            for p in session.query(Product).order_by(Product.id).all()
        ]


def find_products_below_reorder_point():
    """
    Used by the scheduled scanner (scripts/event_simulator.py) to raise
    INVENTORY_LEVEL_CHANGED events for products that need attention.
    """
    with get_session() as session:
        rows = session.query(Inventory).filter(Inventory.quantity < Inventory.reorder_point).all()
        return [
            {'product_id': r.product_id, 'quantity': r.quantity, 'reorder_point': r.reorder_point}
            for r in rows
        ]


# ---------------------------------------------------------------------------
# WRITE HELPERS (called only from governance.py, inside its transaction)
# ---------------------------------------------------------------------------

def add_purchase_order(session, supplier_id, product_id, quantity):
    """Insert a purchase order in the caller's transaction and return its id."""
    po = PurchaseOrder(
        supplier_id=supplier_id,
        product_id=product_id,
        quantity=quantity,
        status='pending',
        created_at=utcnow()
    )
    session.add(po)
    session.flush()
    return po.id


def add_decision_log(session, agent_name, decision, reasoning):
    """Append to the original free-text decision_log in the caller's transaction."""
    entry = DecisionLog(
        agent_name=agent_name,
        decision=decision,
        reasoning=reasoning,
        timestamp=utcnow()
    )
    session.add(entry)
    session.flush()
    return entry.id
