"""Seed the in-memory store with realistic mock data on startup."""
from collections import deque
from datetime import datetime, timedelta, timezone
import random

import store

MACHINES = [
    {"id": "CNC-001", "name": "CNC Lathe Alpha",      "location": "Floor A"},
    {"id": "CNC-002", "name": "CNC Lathe Beta",       "location": "Floor A"},
    {"id": "WLD-001", "name": "Welding Robot 1",      "location": "Floor B"},
    {"id": "WLD-002", "name": "Welding Robot 2",      "location": "Floor B"},
    {"id": "PRS-001", "name": "Hydraulic Press",      "location": "Floor C"},
    {"id": "CNV-001", "name": "Conveyor Belt Main",   "location": "Floor C"},
    {"id": "CMR-001", "name": "Compressor Unit",      "location": "Utility"},
    {"id": "ASM-001", "name": "Assembly Arm 1",       "location": "Floor D"},
]

STATUS_WEIGHTS = {
    "CNC-001": ["running"] * 7 + ["anomaly"] * 2 + ["error"],
    "CNC-002": ["running"] * 6 + ["anomaly"] * 3 + ["error"],
    "WLD-001": ["running"] * 8 + ["anomaly"],
    "WLD-002": ["running"] * 5 + ["anomaly"] * 3 + ["error"] * 2,
    "PRS-001": ["running"] * 6 + ["anomaly"] * 3 + ["offline"],
    "CNV-001": ["running"] * 9,
    "CMR-001": ["running"] * 4 + ["anomaly"] * 4 + ["error"] * 2,
    "ASM-001": ["offline"] * 3 + ["running"] * 5 + ["anomaly"] * 2,
}

CURRENT_STATUS = {
    "CNC-001": "running",
    "CNC-002": "anomaly",
    "WLD-001": "running",
    "WLD-002": "error",
    "PRS-001": "running",
    "CNV-001": "running",
    "CMR-001": "anomaly",
    "ASM-001": "offline",
}


def _metrics(status: str, mid: str) -> dict:
    if status == "offline":
        return {"temperature": None, "vibration": None, "power_consumption": None}
    base_temp   = {"CNC-001": 68, "CNC-002": 65, "WLD-001": 95, "WLD-002": 92,
                   "PRS-001": 55, "CNV-001": 40, "CMR-001": 75, "ASM-001": 50}
    base_vib    = {"CNC-001": 2.1, "CNC-002": 1.9, "WLD-001": 4.5, "WLD-002": 4.2,
                   "PRS-001": 3.0, "CNV-001": 1.2, "CMR-001": 2.8, "ASM-001": 1.5}
    base_power  = {"CNC-001": 12, "CNC-002": 11, "WLD-001": 22, "WLD-002": 20,
                   "PRS-001": 35, "CNV-001": 8,  "CMR-001": 18, "ASM-001": 9}
    multiplier = 1.3 if status == "error" else (0.4 if status == "anomaly" else 1.0)
    return {
        "temperature":        round(base_temp[mid]  * multiplier + random.uniform(-3, 3), 1),
        "vibration":          round(base_vib[mid]   * multiplier + random.uniform(-0.2, 0.2), 2),
        "power_consumption":  round(base_power[mid] * multiplier + random.uniform(-1, 1), 1),
    }


def seed():
    now = datetime.now(timezone.utc)
    for m in MACHINES:
        mid = m["id"]
        history: deque = deque(maxlen=store.MAX_HISTORY)
        prev_status = None

        # Generate 48 h of heartbeats every 5 min  → 576 records
        for i in range(576, 0, -1):
            ts = now - timedelta(minutes=i * 5)
            status = random.choice(STATUS_WEIGHTS[mid])
            metrics = _metrics(status, mid)
            record = {
                "machine_id": mid,
                "timestamp": ts.isoformat(),
                "status": status,
                "health_metrics": metrics,
                "metadata": {"name": m["name"], "location": m["location"]},
            }
            history.append(record)

            # Seed alerts for transitions
            if prev_status and prev_status != status and status in ("error", "offline"):
                store.alerts.append({
                    "machine_id": mid,
                    "timestamp": ts.isoformat(),
                    "alert_type": "error_state" if status == "error" else "went_offline",
                    "previous_status": prev_status,
                    "current_status": status,
                    "message": f"{m['name']} transitioned from {prev_status} → {status}",
                })
            prev_status = status

        # Force the most-recent heartbeat to match CURRENT_STATUS
        current = CURRENT_STATUS[mid]
        latest_metrics = _metrics(current, mid)
        latest_record = {
            "machine_id": mid,
            "timestamp": now.isoformat(),
            "status": current,
            "health_metrics": latest_metrics,
            "metadata": {"name": m["name"], "location": m["location"]},
        }
        history.append(latest_record)
        store.heartbeat_history[mid] = history

        store.machines[mid] = {
            "machine_id": mid,
            "name": m["name"],
            "location": m["location"],
            "status": current,
            "last_heartbeat": now.isoformat(),
            "health_metrics": latest_metrics,
            "metadata": {"name": m["name"], "location": m["location"]},
        }
