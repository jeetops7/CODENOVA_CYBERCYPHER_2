import streamlit as st
import pandas as pd
import sys
import os
from datetime import datetime

# Add the project root to sys.path to allow imports from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.simulator import LogisticsSimulator
from ui.components import risk_indicator, shipment_map_placeholder, action_timeline

# Setup page config
st.set_page_config(
    page_title="LogiFlow Sentinel - Live Operations",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Session State
if 'simulator' not in st.session_state:
    st.session_state.simulator = LogisticsSimulator()
    st.session_state.current_tick = 0
    st.session_state.shipments = st.session_state.simulator.shipments
    st.session_state.active_events = []
    st.session_state.action_log = []
    st.session_state.agent_reasoning = "System Initialized. Awaiting first simulation tick."

def run_next_step():
    """Advances the simulation by one tick and simulates agent actions."""
    st.session_state.current_tick += 1
    
    # 1. Advance Simulation
    shipments, active_events = st.session_state.simulator.simulate_step()
    st.session_state.shipments = shipments
    st.session_state.active_events = active_events
    
    # 2. Simulate Agent Action (Placeholder until agent.py is built)
    # In a real run, you'd pass the new state to the agent here.
    timestamp = datetime.now().strftime("%H:%M:%S")
    reasoning_text = f"[{timestamp}] TICK {st.session_state.current_tick}\n"
    reasoning_text += "Analyzing current shipment state...\n"
    
    if active_events:
        reasoning_text += f"Detected {len(active_events)} active disaster(s)!\n"
        for event in active_events:
            reasoning_text += f"- Reviewing impact of {event['type']} (Severity: {event['severity']})\n"
            
            # Simulate an action for the first affected shipment
            if event.get('affected_shipments'):
                target_shipment = event['affected_shipments'][0]
                action_msg = f"Rerouted {target_shipment} due to {event['type']}"
                st.session_state.action_log.insert(0, {
                    "time": timestamp,
                    "action": "REROUTE",
                    "details": action_msg
                })
                reasoning_text += f"- DECISION: Rerouting {target_shipment} to bypass congestion.\n"
    else:
        reasoning_text += "No critical alerts. Monitoring standard flow.\n"
        # Occasionally log a routine action
        if st.session_state.current_tick % 3 == 0:
            st.session_state.action_log.insert(0, {
                 "time": timestamp,
                 "action": "PRIORITIZE",
                 "details": "Routine SLA priority update for upcoming shipments."
            })
            reasoning_text += "- DECISION: Routine SLA re-prioritization executed.\n"
            
    st.session_state.agent_reasoning = reasoning_text + "\n" + st.session_state.agent_reasoning

# --- SIDEBAR ---
with st.sidebar:
    st.title("🛡️ LogiFlow Sentinel")
    st.subheader("Live Operations")
    
    st.metric("Simulation Time (Tick)", st.session_state.current_tick)
    st.metric("Active Shipments", len(st.session_state.shipments))
    st.metric("Critical Alerts", len(st.session_state.active_events))
    
    st.markdown("---")
    if st.button("Run Next Simulation Step", use_container_width=True, type="primary"):
        run_next_step()
        st.rerun()

    st.markdown("---")
    if st.button("Reset Simulation", use_container_width=True):
        st.session_state.simulator = LogisticsSimulator()
        st.session_state.current_tick = 0
        st.session_state.shipments = st.session_state.simulator.shipments
        st.session_state.active_events = []
        st.session_state.action_log = []
        st.session_state.agent_reasoning = "System Initialized. Awaiting first simulation tick."
        st.rerun()

# --- MAIN AREA ---
st.header("Global Logistics Feed")

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Real-time Shipment Status")
    
    # Format data for the dataframe
    df = pd.DataFrame(st.session_state.shipments)
    
    # Apply some basic styling based on status
    def color_status(val):
        color = ''
        if val == 'DELAYED':
            color = 'background-color: #ffcccc; color: #cc0000'
        elif val == 'IN_TRANSIT':
            color = 'background-color: #e6f2ff; color: #0066cc'
        elif val == 'AT_CHECKPOINT':
            color = 'background-color: #e6ffe6; color: #008000'
        return color
        
    if not df.empty:
        # Reorder columns for better readibility
        cols = ['shipment_id', 'status', 'origin', 'destination', 'warehouse_checkpoint', 'carrier', 'sla_hours']
        df_display = df[cols]
        
        # Display the styled dataframe
        st.dataframe(
            df_display.style.map(color_status, subset=['status']),
            use_container_width=True,
            hide_index=True,
            height=300
        )
    else:
        st.info("No shipments loaded in the system.")
        
    st.markdown("---")
    shipment_map_placeholder(st.session_state.shipments)

with col2:
    st.subheader("Risk Alerts")
    if st.session_state.active_events:
        for event in st.session_state.active_events:
            severity = event.get('severity', 'LOW')
            risk_indicator(severity)
            
            st.markdown(f"**{event['type']}**\n\n"
                     f"{event['description']}\n\n"
                     f"*Affected: {', '.join(event.get('affected_shipments', []))}*")
            st.markdown("---")
    else:
        st.success("No active disaster scenarios. Network operates nominally.", icon="✅")

st.markdown("---")

col3, col4 = st.columns(2)

with col3:
    st.subheader("Agent Reasoning Log")
    with st.expander("View Full Chain-of-Thought", expanded=True):
        st.code(st.session_state.agent_reasoning, language="text")

with col4:
    action_timeline(st.session_state.action_log)


