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

# Paths to data
DATA_DIR = Path(__file__).parent.parent / "data"
SHIPMENTS_FILE = DATA_DIR / "shipment_data.json"
SCENARIOS_FILE = DATA_DIR / "disaster_scenario.json"


class LogisticsSimulator:
    """Simulates a live logistics feed by advancing time and injecting disaster events."""
    
    def __init__(self):
        self.shipments = self._load_data(SHIPMENTS_FILE)
        self.scenarios = self._load_data(SCENARIOS_FILE)
        self.current_tick = 0
        self.active_events = []
        
        # Copy to allow popping scenarios without modifying the original data on disk
        self.available_scenarios = list(self.scenarios)
        
        # Determine the next tick to inject a disaster (4-6 steps)
        self.next_disaster_tick = random.randint(4, 6)
        
    def _load_data(self, filepath: Path) -> List[Dict[str, Any]]:
        """Helper to load JSON data files."""
        if not filepath.exists():
            print(f"Warning: Data file {filepath} not found. Returning empty list.")
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def simulate_step(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Advances the simulation by 1 'tick', updating shipment statuses and ETAs,
        and optionally injecting disaster events.
        
        Returns:
            Tuple containing the updated list of shipments and active events.
        """
        self.current_tick += 1
        
        # Randomly inject 1 disaster event if the tick matches next_disaster_tick
        if self.current_tick == self.next_disaster_tick and self.available_scenarios:
            new_event = random.choice(self.available_scenarios)
            self.available_scenarios.remove(new_event)
            self.active_events.append(new_event)
            
            print(f"\n[TICK {self.current_tick}] DISASTER INJECTED: "
                  f"{new_event['type']} - {new_event['description']} "
                  f"(Severity: {new_event['severity']})")
                  
            # Schedule the next disaster
            self.next_disaster_tick = self.current_tick + random.randint(4, 6)
            
        # Determine which shipments are affected by active active events
        affected_ids = set()
        for event in self.active_events:
            affected_ids.update(event.get('affected_shipments', []))
            
        # Update state for all shipments
        for shipment in self.shipments:
            sid = shipment['shipment_id']
            
            if sid in affected_ids:
                # If shipment is part of an active disaster event
                if shipment['status'] != 'DELAYED':
                    print(f"   Shipment {sid} is now DELAYED due to an active event.")
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
                    print(f"   Error parsing date for {sid}: {e}")
            else:
                # Normal progression for unaffected shipments
                if shipment['status'] == 'IN_TRANSIT':
                    if random.random() < 0.2: # 20% chance to reach checkpoint
                        shipment['status'] = 'AT_CHECKPOINT'
                        print(f"   Shipment {sid} arrived at {shipment['warehouse_checkpoint']}.")
                elif shipment['status'] == 'AT_CHECKPOINT':
                    if random.random() < 0.3: # 30% chance to depart
                        shipment['status'] = 'IN_TRANSIT'
                        print(f"   Shipment {sid} departed {shipment['warehouse_checkpoint']}.")
                elif shipment['status'] == 'DELAYED':
                    # Sometimes things recover if they are no longer in an active event
                    # However here, they aren't in affected_ids, meaning they were delayed 
                    # beforehand or the event was resolved (if we supported resolving).
                    if random.random() < 0.1: # 10% chance to recover naturally
                        shipment['status'] = 'IN_TRANSIT'
                        print(f"   Shipment {sid} recovered from delay.")
                        
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
    print(f"--- Starting Live Logistics Feed Simulation ({steps} steps) ---")
    
    for step in range(1, steps + 1):
        print(f"\n=== Simulation Tick {step} ===")
        shipments, active_events = simulator.simulate_step()
        
        # Yield the current batch
        yield shipments, active_events
        
        # Brief sleep to simulate live feed interval
        time.sleep(0.5)


if __name__ == "__main__":
    # Test execution
    for current_shipments, events in run_simulation(steps=15):
        pass
