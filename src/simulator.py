"""
LogiFlow Sentinel - Real-time Event Simulator

This module acts as a real-time event generator, advancing the state of shipments
and injecting disaster scenarios randomly to simulate a live logistics feed.
"""

import json
import random
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Generator
from pathlib import Path

VERBOSE = False


def _log(*args):
    if VERBOSE:
        print(*args)


DATA_EPOCH = datetime(2026, 3, 9, 12)
HOURS_PER_TICK = 3

# Paths to data
DATA_DIR = Path(__file__).parent.parent / "data"
SHIPMENTS_FILE = DATA_DIR / "shipment_data.json"
SCENARIOS_FILE = DATA_DIR / "disaster_scenario.json"


class LogisticsSimulator:
    """Simulates a live logistics feed by advancing time and injecting disaster events."""
    
    def __init__(self, seed: int = None):
        if seed is not None:
            random.seed(seed)
        self.shipments = self._load_data(SHIPMENTS_FILE)
        # Data is authored around DATA_EPOCH; shift every timestamp so the scenario is "happening now"
        self.start = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        shift = self.start - DATA_EPOCH
        for sh in self.shipments:
            for key in ("shipped_at", "planned_eta", "current_eta"):
                if sh.get(key):
                    sh[key] = (datetime.fromisoformat(sh[key].replace("Z", "")) + shift).isoformat() + "Z"
        self.scenarios = self._load_data(SCENARIOS_FILE)
        self._templates = [dict(sh) for sh in self.shipments]  # lanes new shipments are dispatched on
        self._next_id = 1 + max(int(sh["shipment_id"][4:]) for sh in self.shipments)
        self.current_tick = 0
        self.active_events = []
        
        # Copy to allow popping scenarios without modifying the original data on disk
        self.available_scenarios = list(self.scenarios)
        
        # Determine the next tick to inject a disaster (4-6 steps)
        self.next_disaster_tick = random.randint(1, 2)
        
    def _load_data(self, filepath: Path) -> List[Dict[str, Any]]:
        """Helper to load JSON data files."""
        if not filepath.exists():
            _log(f"Warning: Data file {filepath} not found. Returning empty list.")
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def _dispatch_new(self) -> None:
        """New shipments leave on existing lanes every tick, so the network stays busy."""
        for tpl in random.sample(self._templates, k=min(len(self._templates), random.randint(3, 6))):
            total = tpl.get("sla_hours", 72) * random.uniform(0.8, 1.0)
            eta = (self.clock + timedelta(hours=total)).isoformat() + "Z"
            self.shipments.append({
                **{k: v for k, v in tpl.items() if k not in ("mitigated", "escalated", "priority")},
                "shipment_id": f"SHP-{self._next_id}", "status": "IN_TRANSIT",
                "shipped_at": self.clock.isoformat() + "Z", "planned_eta": eta, "current_eta": eta,
            })
            self._next_id += 1

    def _arrived(self, shipment: Dict[str, Any]) -> bool:
        """A shipment is delivered once the simulated clock passes its (possibly delayed) ETA."""
        try:
            return self.clock >= datetime.fromisoformat(shipment["current_eta"].replace("Z", ""))
        except (KeyError, ValueError):
            return False

    @property
    def clock(self) -> datetime:
        """Simulated wall-clock time (advances HOURS_PER_TICK per tick)."""
        return self.start + timedelta(hours=HOURS_PER_TICK * self.current_tick)

    def inject_event(self, event_id: str) -> Dict[str, Any]:
        """Manually trigger a scenario (used by the demo UI). Returns the event or {}."""
        for event in self.available_scenarios:
            if event["event_id"] == event_id:
                self.available_scenarios.remove(event)
                event["started_tick"] = self.current_tick
                self.active_events.append(event)
                return event
        return {}

    def simulate_step(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Advances the simulation by 1 'tick', updating shipment statuses and ETAs,
        and optionally injecting disaster events.
        
        Returns:
            Tuple containing the updated list of shipments and active events.
        """
        self.current_tick += 1

        # Disruptions clear after their duration; affected shipments then recover naturally
        for event in list(self.active_events):
            if self.current_tick - event.get("started_tick", 0) >= event.get("duration_ticks", 8):
                self.active_events.remove(event)

        # Randomly inject 1 disaster event if the tick matches next_disaster_tick
        if self.current_tick == self.next_disaster_tick and self.available_scenarios:
            new_event = random.choice(self.available_scenarios)
            self.available_scenarios.remove(new_event)
            new_event["started_tick"] = self.current_tick
            self.active_events.append(new_event)

            _log(f"\n[TICK {self.current_tick}] DISASTER INJECTED: "
                  f"{new_event['type']} - {new_event['description']} "
                  f"(Severity: {new_event['severity']})")
                  
            # Schedule the next disaster
            self.next_disaster_tick = self.current_tick + random.randint(3, 5)
            
        # Determine which shipments are affected by active active events
        affected_ids = set()
        for event in self.active_events:
            affected_ids.update(event.get('affected_shipments', []))
        # Shipments the agent has already mitigated stop accruing delay
        affected_ids -= {s['shipment_id'] for s in self.shipments if s.get('mitigated')}
            
        # Update state for all shipments
        for shipment in self.shipments:
            sid = shipment['shipment_id']

            if shipment['status'] == 'DELIVERED':
                continue
            if sid not in affected_ids and self._arrived(shipment):
                shipment['status'] = 'DELIVERED'
                shipment['delivered_tick'] = self.current_tick
                continue

            if sid in affected_ids:
                # If shipment is part of an active disaster event
                if shipment['status'] != 'DELAYED':
                    _log(f"   Shipment {sid} is now DELAYED due to an active event.")
                    shipment['status'] = 'DELAYED'
                
                # Update ETA due to delay
                try:
                    # Parse current ETA, removing the 'Z' for UTC
                    eta_str = shipment['current_eta'].replace('Z', '')
                    old_eta = datetime.fromisoformat(eta_str)
                    
                    # Add arbitrary delay of 2 hours per tick of active disaster
                    new_eta = old_eta + timedelta(hours=2)
                    shipment['current_eta'] = new_eta.isoformat() + "Z"
                except ValueError as e:
                    _log(f"   Error parsing date for {sid}: {e}")
            else:
                # Normal progression for unaffected shipments
                if shipment['status'] == 'IN_TRANSIT':
                    if random.random() < 0.2: # 20% chance to reach checkpoint
                        shipment['status'] = 'AT_CHECKPOINT'
                        _log(f"   Shipment {sid} arrived at {shipment['warehouse_checkpoint']}.")
                elif shipment['status'] == 'AT_CHECKPOINT':
                    if random.random() < 0.3: # 30% chance to depart
                        shipment['status'] = 'IN_TRANSIT'
                        _log(f"   Shipment {sid} departed {shipment['warehouse_checkpoint']}.")
                elif shipment['status'] == 'DELAYED':
                    # Sometimes things recover if they are no longer in an active event
                    # However here, they aren't in affected_ids, meaning they were delayed 
                    # beforehand or the event was resolved (if we supported resolving).
                    if random.random() < 0.1: # 10% chance to recover naturally
                        shipment['status'] = 'IN_TRANSIT'
                        _log(f"   Shipment {sid} recovered from delay.")
                        
        # keep the payload bounded: forget shipments delivered a while ago, then dispatch new ones
        self.shipments[:] = [x for x in self.shipments
                             if x["status"] != "DELIVERED" or self.current_tick - x.get("delivered_tick", self.current_tick) < 10]
        self._dispatch_new()
        return self.shipments, self.active_events


def run_simulation(steps: int = 20) -> Generator[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]], None, None]:
    """
    Generator that runs the logistics simulation for a designated number of steps.
    
    Args:
        steps: Total number of ticks/steps to run the simulation.
        
    Yields:
        Tuple containing the updated shipment list and active scenario list.
    """
    simulator = LogisticsSimulator()
    _log(f"--- Starting Live Logistics Feed Simulation ({steps} steps) ---")
    
    for step in range(1, steps + 1):
        _log(f"\n=== Simulation Tick {step} ===")
        shipments, active_events = simulator.simulate_step()
        
        # Yield the current batch
        yield shipments, active_events
        
        # Brief sleep to simulate live feed interval
        time.sleep(0.5)


if __name__ == "__main__":
    # Test execution
    for current_shipments, events in run_simulation(steps=15):
        pass
