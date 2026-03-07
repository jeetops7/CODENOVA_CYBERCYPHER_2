# LogiFlow Sentinel Architecture

## Overview
LogiFlow Sentinel is a real-time logistics monitoring and autonomous resolution system designed to track shipments and respond to disaster events using an AI Agent.

## System Flow

1. **Simulator (Live Feed)**
   - `src/simulator.py` generates a live feed of tracking updates.
   - Loads baseline data from `shipment_data.json`.
   - Injects randomized disaster scenarios from `disaster_scenario.json`.
   - Advances time and maintains state per tick.

2. **User Interface (Dashboard)**
   - `ui/dashboard.py` (Streamlit) pulls state from the Simulator.
   - Displays real-time shipment table, active alerts, and map placeholders.
   - Shows the Agent's Chain of Thought reasoning and a Timeline of actions taken.

3. **Autonomous Agent (Brain)**
   - *To be implemented in `src/agent.py`*.
   - Monitors the live state for Critical/High severity events.
   - Utilizes `data/knowledge_base.txt` to determine policy-compliant actions.
   - Executes structural decisions based on ReAct architecture.

4. **Tools Layer**
   - `src/tools.py` provides simulation-safe execution functions for the Agent.
   - Functions include: `reroute_shipment`, `prioritize_shipment`, `reassign_carrier`, `escalate_to_operator`, and `log_action`.
   - Contains guardrails to prevent impossible actions (e.g., rerouting a delivered package).

## Data Flow Diagram (Conceptual)
`[Data JSONs] --> [Simulator] <--> [Streamlit Dashboard UI]`
`                      ^                       |`
`                      |                       v`
`                 [Tools Layer] <--- [Autonomous Agent]`
`                                              |`
`                                       [Knowledge Base]`
