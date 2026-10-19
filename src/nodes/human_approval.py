from state import SupplyChainState
from db_service import log_decision


def human_approval_node(state: SupplyChainState) -> dict:
    """
    Simulated human approval node - NO LLM.
    
    In production, this would:
    - Send notification to human operator (email, Slack, dashboard alert)
    - Pause workflow and wait for human response
    - Accept approval/rejection/modification input
    
    For MVP, we simulate automatic approval after logging the request.
    
    Args:
        state: Current graph state with final_decision
        
    Returns:
        Partial state update with human_feedback
    """
    final_decision = state.get('final_decision', {})
    decision_type = final_decision.get('decision_type', 'HOLD')
    details = final_decision.get('details', {})
    explanation = final_decision.get('explanation', '')
    decision_risk = state.get('decision_risk', 'UNKNOWN')
    
    # Extract decision details for logging
    supplier_id = details.get('supplier_id')
    quantity = details.get('quantity', 0)
    expedite = details.get('expedite', False)
    
    # Build approval request message
    approval_request = (
        f"HIGH RISK DECISION REQUIRES APPROVAL:\n"
        f"Decision: {decision_type}\n"
        f"Supplier ID: {supplier_id}\n"
        f"Quantity: {quantity} units\n"
        f"Expedite: {expedite}\n"
        f"Risk Level: {decision_risk}\n"
        f"Explanation: {explanation}"
    )
    
    # Log the approval request to database
    approval_log_id = log_decision(
        agent_name='system',
        decision='HUMAN_APPROVAL_REQUESTED',
        reasoning=approval_request
    )
    
    # ================================================================
    # PRODUCTION CODE (commented out for MVP)
    # ================================================================
    # 
    # import os
    # import requests
    # from datetime import datetime
    # 
    # # Option 1: Email notification
    # def send_email_approval_request(approval_data):
    #     """Send email to approver with decision details."""
    #     import smtplib
    #     from email.mime.text import MIMEText
    #     
    #     msg = MIMEText(approval_data['message'])
    #     msg['Subject'] = f"[URGENT] Supply Chain Approval Required - {approval_data['decision_id']}"
    #     msg['From'] = os.getenv('EMAIL_FROM')
    #     msg['To'] = os.getenv('APPROVER_EMAIL')
    #     
    #     with smtplib.SMTP(os.getenv('SMTP_SERVER'), 587) as server:
    #         server.starttls()
    #         server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD'))
    #         server.send_message(msg)
    # 
    # 
    # # Option 2: Slack notification
    # def send_slack_approval_request(approval_data):
    #     """Send Slack message to approval channel."""
    #     slack_webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    #     
    #     payload = {
    #         'text': f"🚨 *HIGH RISK DECISION REQUIRES APPROVAL*",
    #         'blocks': [
    #             {
    #                 'type': 'section',
    #                 'text': {
    #                     'type': 'mrkdwn',
    #                     'text': f"*Decision ID:* {approval_data['decision_id']}\n"
    #                             f"*Type:* {approval_data['decision_type']}\n"
    #                             f"*Supplier:* {approval_data['supplier_id']}\n"
    #                             f"*Quantity:* {approval_data['quantity']} units\n"
    #                             f"*Risk Level:* {approval_data['risk_level']}"
    #                 }
    #             },
    #             {
    #                 'type': 'actions',
    #                 'elements': [
    #                     {
    #                         'type': 'button',
    #                         'text': {'type': 'plain_text', 'text': '✅ Approve'},
    #                         'style': 'primary',
    #                         'value': f"approve_{approval_data['decision_id']}"
    #                     },
    #                     {
    #                         'type': 'button',
    #                         'text': {'type': 'plain_text', 'text': '❌ Reject'},
    #                         'style': 'danger',
    #                         'value': f"reject_{approval_data['decision_id']}"
    #                     }
    #                 ]
    #             }
    #         ]
    #     }
    #     
    #     requests.post(slack_webhook_url, json=payload)
    # 
    # 
    # # Option 3: Database-backed approval queue
    # def create_approval_record(approval_data):
    #     """Store approval request in database for dashboard pickup."""
    #     from sqlalchemy import Column, Integer, String, DateTime, create_engine
    #     from sqlalchemy.orm import sessionmaker
    #     from models import Base
    #     
    #     # Create ApprovalQueue table if not exists
    #     # class ApprovalQueue(Base):
    #     #     __tablename__ = 'approval_queue'
    #     #     id = Column(Integer, primary_key=True)
    #     #     decision_log_id = Column(Integer)
    #     #     status = Column(String, default='pending')  # pending, approved, rejected
    #     #     decision_data = Column(String)  # JSON
    #     #     requested_at = Column(DateTime, default=datetime.utcnow)
    #     #     reviewed_at = Column(DateTime, nullable=True)
    #     #     reviewer_email = Column(String, nullable=True)
    #     #     feedback = Column(String, nullable=True)
    #     
    #     engine = create_engine(os.getenv('DATABASE_URL'))
    #     Session = sessionmaker(bind=engine)
    #     session = Session()
    #     
    #     approval_record = ApprovalQueue(
    #         decision_log_id=approval_data['log_id'],
    #         decision_data=json.dumps(approval_data),
    #         status='pending'
    #     )
    #     session.add(approval_record)
    #     session.commit()
    #     approval_id = approval_record.id
    #     session.close()
    #     
    #     return approval_id
    # 
    # 
    # # Option 4: Wait for approval via API/Dashboard
    # def wait_for_human_approval(approval_id, timeout_seconds=3600):
    #     """
    #     Poll database until human provides approval/rejection.
    #     This would typically be called in an async workflow.
    #     """
    #     import time
    #     from db_service import get_session
    #     
    #     start_time = time.time()
    #     
    #     while time.time() - start_time < timeout_seconds:
    #         with get_session() as session:
    #             approval = session.query(ApprovalQueue).filter_by(id=approval_id).first()
    #             
    #             if approval.status == 'approved':
    #                 return 'APPROVED', approval.feedback
    #             elif approval.status == 'rejected':
    #                 return 'REJECTED', approval.feedback
    #         
    #         # Wait 5 seconds before checking again
    #         time.sleep(5)
    #     
    #     # Timeout - default to rejection for safety
    #     return 'TIMEOUT_REJECTED', 'Approval request timed out after 1 hour'
    # 
    # 
    # # PRODUCTION IMPLEMENTATION:
    # approval_data = {
    #     'decision_id': approval_log_id,
    #     'decision_type': decision_type,
    #     'supplier_id': supplier_id,
    #     'quantity': quantity,
    #     'expedite': expedite,
    #     'risk_level': decision_risk,
    #     'message': approval_request,
    #     'log_id': approval_log_id
    # }
    # 
    # # Send notification (choose one or multiple)
    # send_slack_approval_request(approval_data)  # Immediate notification
    # # send_email_approval_request(approval_data)  # Email backup
    # 
    # # Create approval record in database
    # approval_id = create_approval_record(approval_data)
    # 
    # # Wait for human response (this pauses the workflow)
    # human_response, feedback_text = wait_for_human_approval(approval_id)
    # 
    # # Return actual human decision
    # return {
    #     'human_feedback': human_response  # 'APPROVED', 'REJECTED', or 'TIMEOUT_REJECTED'
    # }
    # 
    # ================================================================
    # END PRODUCTION CODE
    # ================================================================
    
    
    # MVP SIMULATION: Auto-approve for testing
    simulated_feedback = "APPROVED"
    
    print("\n" + "="*60)
    print("HUMAN APPROVAL REQUIRED")
    print("="*60)
    print(approval_request)
    print("="*60)
    print(f"SIMULATED RESPONSE: {simulated_feedback}")
    print("="*60 + "\n")
    
    return {
        'human_feedback': simulated_feedback
    }


def post_approval_routing(state: SupplyChainState) -> str:
    """
    Conditional edge function for routing after human approval.
    
    Routes to:
    - "execute" if APPROVED
    - "end" if REJECTED or TIMEOUT_REJECTED
    
    Returns:
        Next node name as string
    """
    human_feedback = state.get('human_feedback', '')
    
    if human_feedback == 'APPROVED':
        return "execute"
    else:
        return "end"
