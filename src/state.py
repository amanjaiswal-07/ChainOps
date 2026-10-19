from typing_extensions import TypedDict, Annotated


def merge_agent_outputs(left: dict, right: dict | None) -> dict:
    """
    Reducer function to safely merge agent outputs.
    Prevents overwriting - appends new agent outputs to existing ones.
    """
    if right is None:
        return left
    return {**left, **right}


def replace_snapshot(left: dict, right: dict | None) -> dict:
    """
    Reducer function for db_snapshot.
    Always replaces with the latest snapshot (no merging needed).
    """
    if right is None:
        return left
    return right


class SupplyChainState(TypedDict):
    """
    Shared state passed between all nodes in the LangGraph workflow.
    
    This state represents the in-memory context for the supply chain decision loop.
    Each node receives this state, processes it, and returns updates.
    
    Reducers control how updates are merged into the state:
    - agent_outputs: Merges new agent outputs with existing ones
    - db_snapshot: Replaces with latest snapshot
    - Other fields: Default overwrite behavior
    """
    product_id: int
    # Current snapshot of database state (read by agents)
    # Reducer: Always replace with latest
    db_snapshot: Annotated[dict, replace_snapshot]
    
    # Outputs from individual agents (keyed by agent name)
    # Reducer: Merge dictionaries to preserve all agent outputs
    agent_outputs: Annotated[dict, merge_agent_outputs]
    
    # Final procurement decision (supplier_id, quantity, reasoning)
    # Default behavior: overwrite
    final_decision: dict | None
    
    # Risk assessment from Risk Agent
    # Default behavior: overwrite
    decision_risk: str | None
    
    # Optional human override or approval
    # Default behavior: overwrite
    human_feedback: str | None
