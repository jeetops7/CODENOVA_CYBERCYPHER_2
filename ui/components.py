import streamlit as st
import pandas as pd
import random

def risk_indicator(severity: str):
    """
    Displays a risk indicator based on the severity.
    
    Args:
        severity (str): The severity level (e.g., 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW').
    """
    severity = severity.upper()
    if severity == 'CRITICAL':
        return st.error(f"**CRITICAL RISK**", icon="🚨")
    elif severity == 'HIGH':
        return st.error(f"**HIGH RISK**", icon="🔴")
    elif severity == 'MEDIUM':
        return st.warning(f"**MEDIUM RISK**", icon="🟡")
    else:
        return st.info(f"**LOW RISK**", icon="🔵")

def shipment_map_placeholder(shipments: list):
    """
    Displays a placeholder map for shipments.
    Since we don't have real coordinates in our data, this generates a conceptual
    matplotlib/plotly map. For demo purposes, we'll use a simple scatter map.
    
    Args:
        shipments (list): List of shipment dictionaries
    """
    if not shipments:
        st.info("No shipments to display on map.")
        return
        
    st.markdown("### 🗺️ Live Network Map (Simulated)")
    
    # Generate some dummy coordinates for a map based on shipments
    # In a real app, origin/destination would be geocoded
    map_data = []
    
    # Common US coordinates roughly
    coords = {
        "Los Angeles, CA": (34.05, -118.24),
        "New York, NY": (40.71, -74.00),
        "Chicago, IL": (41.87, -87.62),
        "Houston, TX": (29.76, -95.36),
        "Phoenix, AZ": (33.44, -112.07),
        "Denver, CO": (39.73, -104.99),
        "Seattle, WA": (47.60, -122.33),
        "Miami, FL": (25.76, -80.19),
        "Atlanta, GA": (33.74, -84.38),
        "Boston, MA": (42.36, -71.05),
        "Dallas, TX": (32.77, -96.79),
        "Austin, TX": (30.26, -97.74),
        "San Francisco, CA": (37.77, -122.41)
    }
    
    for s in shipments:
        # Just pick origin or destination randomly to show dots on the map
        loc = s.get('origin') if random.random() > 0.5 else s.get('destination')
        if loc in coords:
            lat, lon = coords[loc]
            # Add some jitter so points don't perfectly overlap
            lat += random.uniform(-1, 1)
            lon += random.uniform(-1, 1)
            
            # Determine color based on status
            color = "#0000ff" # Blue (Transit)
            if s['status'] == 'DELAYED':
                color = "#ff0000" # Red
            elif s['status'] == 'AT_CHECKPOINT':
                color = "#00ff00" # Green
                
            map_data.append({
                "lat": lat,
                "lon": lon,
                "color": color,
                "shipment": s['shipment_id']
            })
            
    if map_data:
        df = pd.DataFrame(map_data)
        st.map(df, latitude="lat", longitude="lon", color="color", size=100)
    else:
        st.caption("Map data currently unavailable.")

def action_timeline(history: list):
    """
    Displays the timeline of actions taken by the agent.
    
    Args:
        history (list): A list of dictionary objects representing actions.
    """
    st.subheader("Action Timeline")
    
    if not history:
        st.caption("No actions executed yet.")
        return
        
    for log in history[:10]: # show last 10
        action_color = "blue"
        if log['action'] == "REROUTE":
            action_color = "orange"
        elif log['action'] == "ESCALATE":
            action_color = "red"
            
        st.markdown(f"**[{log['time']}]** :{action_color}[{log['action']}] - {log['details']}")
