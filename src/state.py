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


class SupplyChainState(TypedDict, total=False):
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

    # Optional modifications applied on top of the DB snapshot before the
    # agents see it (from an event payload or a simulator scenario).
    # See overlay.py. The database itself is never modified by an overlay.
    overlay: dict | None

    # Current snapshot of database state (read by agents)
    # Reducer: Always replace with latest
    db_snapshot: Annotated[dict, replace_snapshot]

    # Unmodified DB snapshot, kept so the UI can compare baseline vs scenario
    baseline_snapshot: dict | None

    # Result of validation.validate_snapshot(): {status, errors, warnings}
    validation: dict | None

    # Outputs from individual agents (keyed by agent name)
    # Reducer: Merge dictionaries to preserve all agent outputs
    agent_outputs: Annotated[dict, merge_agent_outputs]

    # Final procurement decision (supplier_id, quantity, reasoning)
    # Default behavior: overwrite
    final_decision: dict | None

    # Risk classification from the decision gate, plus the policy rules
    # that produced it (so the audit record can show *why*)
    decision_risk: str | None
    risk_reasons: list | None

    # Set by the routing nodes: AUTO_APPROVED, PENDING_APPROVAL,
    # NO_ACTION_REQUIRED or VALIDATION_FAILED. Execution is NOT done in
    # the graph; governance.py performs it after the graph finishes.
    approval_status: str | None

    # Kept for backward compatibility with the original UI/CLI
    human_feedback: str | None
