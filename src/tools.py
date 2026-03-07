"""
LogiFlow Sentinel - Simulation Tools
Pure simulation functions for the AI agent to interact with the simulated environment.
"""

from typing import Dict, Any
from datetime import datetime

# Simulated database state for guardrails
_SIMULATED_DB = {
    # Keep track of delivered shipments to enforce guardrails
    "DELIVERED_SHIPMENTS": set()
}

def _check_if_delivered(shipment_id: str) -> bool:
    """Internal helper to check if a shipment is already delivered."""
    return shipment_id in _SIMULATED_DB["DELIVERED_SHIPMENTS"]

def log_action(shipment_id: str, action_type: str, details: str) -> Dict[str, Any]:
    """
    Records an action taken on a shipment in the audit log.
    
    Args:
        shipment_id (str): The ID of the shipment.
        action_type (str): The category of the action (e.g., 'REROUTE', 'ESCALATION').
        details (str): Detailed description of what was done.
        
    Returns:
        dict: The result of the logging operation.
    """
    timestamp = datetime.now().isoformat()
    log_msg = f"[{timestamp}] ACTION LOGGED | Shipment: {shipment_id} | Type: {action_type} | Details: {details}"
    print(log_msg)
    
    return {
        "status": "success",
        "operation": "log_action",
        "shipment_id": shipment_id,
        "timestamp": timestamp,
        "recorded_details": details
    }

def reroute_shipment(shipment_id: str, new_route: str) -> Dict[str, Any]:
    """
    Reroutes a shipment to a new destination or via a new checkpoint.
    
    Args:
        shipment_id (str): The ID of the shipment to reroute.
        new_route (str): The new route or checkpoint designation.
        
    Returns:
        dict: Result of the reroute operation.
    """
    if _check_if_delivered(shipment_id):
        print(f"FAILED: Cannot reroute {shipment_id} - Shipment already delivered.")
        return {"status": "error", "message": "Shipment already delivered"}
        
    print(f"SUCCESS: Shipment {shipment_id} successfully rerouted to {new_route}.")
    log_action(shipment_id, "REROUTE", f"Rerouted to {new_route}")
    
    return {
        "status": "success",
        "operation": "reroute",
        "shipment_id": shipment_id,
        "new_route": new_route
    }

def prioritize_shipment(shipment_id: str, new_priority: int) -> Dict[str, Any]:
    """
    Adjusts the operational priority of a shipment.
    
    Args:
        shipment_id (str): The ID of the shipment.
        new_priority (int): The new priority level (e.g., 1 = Highest, 5 = Lowest).
        
    Returns:
        dict: Result of the prioritization operation.
    """
    if _check_if_delivered(shipment_id):
        print(f"FAILED: Cannot change priority for {shipment_id} - Shipment already delivered.")
        return {"status": "error", "message": "Shipment already delivered"}
        
    print(f"SUCCESS: Shipment {shipment_id} priority updated to {new_priority}.")
    log_action(shipment_id, "PRIORITIZE", f"Priority set to {new_priority}")
    
    return {
        "status": "success",
        "operation": "prioritize",
        "shipment_id": shipment_id,
        "new_priority": new_priority
    }

def reassign_carrier(shipment_id: str, new_carrier: str) -> Dict[str, Any]:
    """
    Assigns a different carrier to handle the shipment.
    
    Args:
        shipment_id (str): The ID of the shipment.
        new_carrier (str): The name of the new carrier company.
        
    Returns:
        dict: Result of the reassign operation.
    """
    if _check_if_delivered(shipment_id):
        print(f"FAILED: Cannot reassign carrier for {shipment_id} - Shipment already delivered.")
        return {"status": "error", "message": "Shipment already delivered"}
        
    print(f"SUCCESS: Carrier for shipment {shipment_id} reassigned to {new_carrier}.")
    log_action(shipment_id, "REASSIGN_CARRIER", f"Carrier changed to {new_carrier}")
    
    return {
        "status": "success",
        "operation": "reassign_carrier",
        "shipment_id": shipment_id,
        "new_carrier": new_carrier
    }

def escalate_to_operator(shipment_id: str, reason: str) -> Dict[str, Any]:
    """
    Escalates a complex or unresolvable issue to a human operator.
    
    Args:
        shipment_id (str): The ID of the problematic shipment.
        reason (str): The explanation for why human intervention is needed.
        
    Returns:
        dict: Result of the escalation operation.
    """
    if not reason.strip():
        print(f"FAILED: Escalation for {shipment_id} requires a valid reason.")
        return {"status": "error", "message": "Escalation reason cannot be empty"}
        
    print(f"ESCALATION ALERT: Shipment {shipment_id} escalated to human operator. Reason: {reason}")
    log_action(shipment_id, "ESCALATE", f"Escalated to operator: {reason}")
    
    return {
        "status": "success",
        "operation": "escalate",
        "shipment_id": shipment_id,
        "reason": reason,
        "operator_notified": True
    }
