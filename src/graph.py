from langgraph.graph import StateGraph, END
from state import SupplyChainState

# Import all nodes
from nodes.data_ingestion import data_ingestion_node
from nodes.data_validation import data_validation_node, route_after_validation, validation_failed_node
from nodes.decision_gate import decision_gate_node, should_request_human_approval
from nodes.human_approval import human_approval_node, auto_approve_node

# Import all agents
from agents.demand_agent import demand_agent_node
from agents.inventory_agent import inventory_agent_node
from agents.risk_agent import risk_agent_node
from agents.logistics_agent import logistics_agent_node
from agents.coordinator_agent import coordinator_agent_node

AGENT_NODES = ["demand_agent", "inventory_agent", "risk_agent", "logistics_agent", "coordinator"]


def create_supply_chain_graph():
    """
    Create the LangGraph workflow for the supply chain control tower.

    Flow:
    1. Data Ingestion (read DB snapshot, apply event/scenario overlay)
    2. Data Validation (business rules; invalid data ends the cycle here)
    3. Agent Analysis (sequential, each agent reads the previous outputs):
       - Demand Agent
       - Inventory Agent
       - Risk Agent
       - Logistics Agent
    4. Coordinator Agent (synthesize decision)
    5. Decision Gate (explicit risk policy)
    6. Auto-approve OR Human Approval (pause)

    The graph has no side effects. Execution of an approved decision is
    done afterwards by governance.py, so a recommendation is never
    executed just because it was generated.

    Returns:
        Compiled LangGraph StateGraph
    """

    # Initialize graph with state schema
    workflow = StateGraph(SupplyChainState)

    # ================================================================
    # ADD NODES
    # ================================================================

    # Data ingestion and validation (entry point)
    workflow.add_node("ingest_data", data_ingestion_node)
    workflow.add_node("validate_data", data_validation_node)
    workflow.add_node("validation_failed", validation_failed_node)

    # Agent nodes (reasoning layer)
    workflow.add_node("demand_agent", demand_agent_node)
    workflow.add_node("inventory_agent", inventory_agent_node)
    workflow.add_node("risk_agent", risk_agent_node)
    workflow.add_node("logistics_agent", logistics_agent_node)
    workflow.add_node("coordinator", coordinator_agent_node)

    # Governance nodes
    workflow.add_node("decision_gate", decision_gate_node)
    workflow.add_node("auto_approve", auto_approve_node)
    workflow.add_node("human_approval", human_approval_node)

    # ================================================================
    # SET ENTRY POINT
    # ================================================================

    workflow.set_entry_point("ingest_data")

    # ================================================================
    # ADD EDGES
    # ================================================================

    workflow.add_edge("ingest_data", "validate_data")

    # Invalid data never reaches an agent
    workflow.add_conditional_edges(
        "validate_data",
        route_after_validation,  # Returns "valid" or "invalid"
        {
            "valid": "demand_agent",
            "invalid": "validation_failed"
        }
    )
    workflow.add_edge("validation_failed", END)

    # Agents run in sequence; later agents read earlier outputs
    workflow.add_edge("demand_agent", "inventory_agent")
    workflow.add_edge("inventory_agent", "risk_agent")
    workflow.add_edge("risk_agent", "logistics_agent")
    workflow.add_edge("logistics_agent", "coordinator")
    workflow.add_edge("coordinator", "decision_gate")

    # Decision gate -> auto-approve OR human approval
    workflow.add_conditional_edges(
        "decision_gate",
        should_request_human_approval,  # Returns "auto_execute" or "human_approval"
        {
            "auto_execute": "auto_approve",
            "human_approval": "human_approval"
        }
    )

    # Both end the graph. A pending decision resumes via governance.approve().
    workflow.add_edge("auto_approve", END)
    workflow.add_edge("human_approval", END)

    # ================================================================
    # COMPILE GRAPH
    # ================================================================

    return workflow.compile()


# The original create_continuous_monitoring_graph() looped execute -> ingest
# with no exit condition. Continuous monitoring is now done by raising events
# (see scripts/event_simulator.py --mode scan), which reuses this graph.
