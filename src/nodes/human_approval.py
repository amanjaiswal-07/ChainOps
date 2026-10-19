"""
Routing outcomes at the end of the graph.

The original project auto-approved every high-risk decision inside this
node. Now the graph only *records the outcome of the policy*:

  human_approval_node   -> PENDING_APPROVAL. The cycle stops here. A person
                           approves or rejects later through the API or UI
                           (governance.approve / governance.reject).
  auto_approve_node     -> AUTO_APPROVED for a low-risk REORDER, or
                           NO_ACTION_REQUIRED for a HOLD.

No node in the graph writes to the database. After the graph finishes,
workflow.py persists the decision record and, only for AUTO_APPROVED,
asks governance.py to execute it.
"""

from state import SupplyChainState


def human_approval_node(state: SupplyChainState) -> dict:
    """High-risk decision: park it for a human. No LLM, no side effects."""
    return {
        'approval_status': 'PENDING_APPROVAL',
        'human_feedback': 'PENDING - Human approval required for HIGH risk decision',
    }


def auto_approve_node(state: SupplyChainState) -> dict:
    """Low-risk decision: approved by policy (REORDER) or nothing to do (HOLD)."""
    decision_type = (state.get('final_decision') or {}).get('decision_type', 'HOLD')
    if decision_type == 'REORDER':
        return {'approval_status': 'AUTO_APPROVED', 'human_feedback': None}
    return {'approval_status': 'NO_ACTION_REQUIRED', 'human_feedback': None}
