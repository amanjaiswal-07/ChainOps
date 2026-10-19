from state import SupplyChainState
from db_service import read_supply_chain_snapshot
from overlay import apply_overlay


def data_ingestion_node(state: SupplyChainState) -> dict:
    """
    Load current supply chain state from database.

    Processes one product at a time based on state['product_id'].
    If not set, defaults to product_id=1.

    If the cycle was started by an event or a simulator scenario, its
    overlay is applied to an in-memory copy of the snapshot. The
    unmodified snapshot is kept as `baseline_snapshot` for comparison.
    """
    # Get product ID from state, default to 1
    product_id = state.get('product_id', 1)

    # Read snapshot for specific product
    baseline = read_supply_chain_snapshot(product_id=product_id)
    snapshot = apply_overlay(baseline, state.get('overlay'))

    return {
        'db_snapshot': snapshot,
        'baseline_snapshot': baseline,
        'agent_outputs': {}
    }
