from state import SupplyChainState
from db_service import create_purchase_order, log_decision


def execution_node(state: SupplyChainState) -> dict:
    """
    Execute the final decision by writing to the database.
    
    This is a deterministic execution node - NO LLM.
    This is the ONLY node (besides data ingestion) that writes to the database.
    
    Responsibilities:
    1. Create purchase order if decision is REORDER
    2. Log the decision and reasoning to decision_log table
    
    Args:
        state: Current graph state with final_decision
        
    Returns:
        Partial state update with execution status
    """
    final_decision = state.get('final_decision', {})
    snapshot = state['db_snapshot']
    
    # Extract decision details
    decision_type = final_decision.get('decision_type', 'HOLD')
    details = final_decision.get('details', {})
    explanation = final_decision.get('explanation', 'No explanation provided')
    
    supplier_id = details.get('supplier_id')
    quantity = details.get('quantity', 0)
    expedite = details.get('expedite', False)
    product_id = snapshot['product']['id']
    
    execution_result = {
        'executed': False,
        'po_id': None,
        'log_id': None,
        'message': ''
    }
    
    try:
        # Execute REORDER decision
        if decision_type == 'REORDER' and supplier_id and quantity > 0:
            # Create purchase order in database
            po_id = create_purchase_order(
                supplier_id=supplier_id,
                product_id=product_id,
                quantity=quantity
            )
            
            # Log the decision
            decision_text = (
                f"REORDER: {quantity} units from supplier {supplier_id}, "
                f"expedite={expedite}"
            )
            log_id = log_decision(
                agent_name='coordinator',
                decision=decision_text,
                reasoning=explanation
            )
            
            execution_result = {
                'executed': True,
                'po_id': po_id,
                'log_id': log_id,
                'message': f'Purchase order #{po_id} created successfully'
            }
        
        # Execute HOLD decision (just log, no PO)
        elif decision_type == 'HOLD':
            # Log the decision to hold
            log_id = log_decision(
                agent_name='coordinator',
                decision='HOLD: No reorder needed',
                reasoning=explanation
            )
            
            execution_result = {
                'executed': True,
                'po_id': None,
                'log_id': log_id,
                'message': 'HOLD decision logged, no purchase order created'
            }
        
        else:
            # Invalid decision state
            execution_result = {
                'executed': False,
                'po_id': None,
                'log_id': None,
                'message': f'Invalid decision: {decision_type}, supplier={supplier_id}, qty={quantity}'
            }
    
    except Exception as e:
        # Handle execution errors
        execution_result = {
            'executed': False,
            'po_id': None,
            'log_id': None,
            'message': f'Execution failed: {str(e)}'
        }
    
    # Return execution status (could be logged or displayed)
    return {
        'agent_outputs': {
            **state['agent_outputs'],
            'execution': execution_result
        }
    }


def human_approval_node(state: SupplyChainState) -> dict:
    """
    Placeholder for human approval workflow.
    
    In a real system, this would:
    - Send notification to human operator
    - Wait for approval/rejection/modification
    - Update state with human_feedback
    
    For MVP: just log that human approval is required.
    """
    final_decision = state.get('final_decision', {})
    decision_type = final_decision.get('decision_type', 'HOLD')
    details = final_decision.get('details', {})
    
    # Log decision awaiting approval
    approval_message = (
        f"Decision requires human approval: {decision_type}, "
        f"supplier={details.get('supplier_id')}, "
        f"quantity={details.get('quantity')}"
    )
    
    log_decision(
        agent_name='system',
        decision='AWAITING_HUMAN_APPROVAL',
        reasoning=approval_message
    )
    
    # In MVP, simulate approval (in production, this would pause and wait)
    return {
        'human_feedback': 'PENDING - Human approval required for HIGH risk decision',
        'agent_outputs': {
            **state['agent_outputs'],
            'execution': {
                'executed': False,
                'message': approval_message
            }
        }
    }
