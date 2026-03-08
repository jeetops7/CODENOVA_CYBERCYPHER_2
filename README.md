# LogiFlow Sentinel 🛡️

## Problem Overview
Global supply chains are increasingly fragile. When disasters strike (storms, strikes, port closures), logistics coordinators are overwhelmed with alerts and struggle to manually reroute shipments before SLAs are breached. 

## Solution
**LogiFlow Sentinel** is an AI-powered autonomous logistics agent that monitors a live supply chain feed. When a disruption occurs, the Agent automatically analyzes the impact, consults the operational knowledge base, and executes tools (rerouting, prioritizing, reassigning) to mitigate delays—all fully observable via a real-time command dashboard.

## Architecture
See `docs/architecture_diagram.md` for a text-based overview of the system flow connecting the Live Simulator, Streamlit Dashboard, and the Autonomous Agent.

## Agent Workflow
The Sentinel agent uses a **ReAct** (Reasoning + Acting) loop:
1. **Observe**: Receives the current state of shipments and active disaster scenarios.
2. **Reason**: Analyzes the severity, identifies affected shipments, and cross-references business rules in the Knowledge Base.
3. **Act**: Calls the appropriate tool (`reroute_shipment`, `reassign_carrier`, etc.) to resolve the issue, or `escalate_to_operator` if the rule cannot be automatically satisfied.

## Demo Instructions
1. Install dependencies: `pip install -r requirements.txt`
2. Start the dashboard: `streamlit run ui/dashboard.py`
3. Click **"Run Next Simulation Step"** in the sidebar.
4. Watch the simulator inject disasters and the agent output its reasoning and actions in real-time.

## Tech Stack
* **UI**: Streamlit, Pandas
* **Simulation**: Pure Python
* **Agent Framework**: LangChain, Ollama (Local LLMs)
* **Knowledge Retrieval**: FAISS (for RAG on operational rules)

## Future Improvements
* Integration with real-world ELD (Electronic Logging Device) APIs.
* Advanced routing algorithms (e.g., Dijkstra's with real-time weather weighting).
* Multi-agent coordination (e.g., dedicated agents per region).






logiflow-sentinel/
├── .devcontainer/          # Containerized development environment config
├── data/                   # Knowledge base and state storage
│   ├── disaster_scenario.json  # Pre-defined simulation events
│   ├── knowledge_base.txt      # Domain-specific logistics rules
│   └── shipment_data.json      # Current state of all active shipments
├── docs/                   # Documentation and design assets
│   ├── architecture_diagram.md
│   └── scalability_plan.md
├── src/                    # Core Agent Logic
│   ├── agent.py            # Main LogisticsAgent class (The "Brain")
│   ├── data_fetcher.py     # Live API integration for Weather/News
│   ├── simulator.py        # Logic for scenario-based demonstrations
│   └── tools.py            # Executable actions (Reroute, Alert, etc.)
├── ui/                     # Presentation Layer
│   ├── components.py       # Reusable Streamlit UI elements
│   └── dashboard.py        # Main conversational Command Center
├── .env                    # Environment variables (API Keys) - DO NOT COMMIT
├── .gitignore              # Files and folders to be ignored by Git
├── README.md               # Project overview and documentation
└── requirements.txt        # Python dependencies
