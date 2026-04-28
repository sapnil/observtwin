"""
Mock heartbeat sender – posts live heartbeats to POST /api/heartbeat every N seconds.
Usage: python mock_sender.py [--url URL] [--interval SECONDS]
"""
import argparse
import random
import time
import base64
from datetime import datetime, timezone

import requests

MACHINES = [
    {"id": "CNC-001", "name": "CNC Lathe Alpha",    "location": "Floor A"},
    {"id": "CNC-002", "name": "CNC Lathe Beta",     "location": "Floor A"},
    {"id": "WLD-001", "name": "Welding Robot 1",    "location": "Floor B"},
    {"id": "WLD-002", "name": "Welding Robot 2",    "location": "Floor B"},
    {"id": "PRS-001", "name": "Hydraulic Press",    "location": "Floor C"},
    {"id": "CNV-001", "name": "Conveyor Belt Main", "location": "Floor C"},
    {"id": "CMR-001", "name": "Compressor Unit",    "location": "Utility"},
    {"id": "ASM-001", "name": "Assembly Arm 1",     "location": "Floor D"},
]

SENSORS = [
    {"id": "CAM-001", "location": "Floor A Zone 1"},
    {"id": "CAM-002", "location": "Floor B Zone 2"},
    {"id": "SMK-001", "location": "Utility Room"},
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

SENSOR_STATUS_WEIGHTS = {
    "CAM-001": ["Normal"] * 5 + ["Human Detected"] * 95,
    "CAM-002": ["Normal"] * 98 + ["Human Detected"] * 2,
    "SMK-001": ["Normal"] * 99 + ["Smoke Detected"] * 1,
}

BASE_METRICS = {
    "CNC-001": (68, 2.1, 12), "CNC-002": (65, 1.9, 11),
    "WLD-001": (95, 4.5, 22), "WLD-002": (92, 4.2, 20),
    "PRS-001": (55, 3.0, 35), "CNV-001": (40, 1.2,  8),
    "CMR-001": (75, 2.8, 18), "ASM-001": (50, 1.5,  9),
}


def _metrics(mid: str, status: str) -> dict:
    if status == "offline":
        return {"temperature": None, "vibration": None, "power_consumption": None}
    t, v, p = BASE_METRICS[mid]
    m = 1.3 if status == "error" else (0.4 if status == "anomaly" else 1.0)
    return {
        "temperature":       round(t * m + random.uniform(-3, 3), 1),
        "vibration":         round(v * m + random.uniform(-0.2, 0.2), 2),
        "power_consumption": round(p * m + random.uniform(-1, 1), 1),
    }


def send_heartbeat(url: str, machine: dict) -> None:
    mid = machine["id"]
    status = random.choice(STATUS_WEIGHTS[mid])
    payload = {
        "machine_id": mid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "health_metrics": _metrics(mid, status),
        "metadata": {"name": machine["name"], "location": machine["location"]},
    }
    try:
        r = requests.post(url, json=payload, timeout=5)
        print(f"[{payload['timestamp']}] {mid:8s} {status:8s} → {r.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  ERROR: could not connect to {url}")


def send_sensor_heartbeat(url: str, sensor: dict) -> None:
    sid = sensor["id"]
    status = random.choice(SENSOR_STATUS_WEIGHTS[sid])
    payload = {
        "sensor_id": sid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    
    # Optionally add a mock image frame for alarms
    if status != "Normal":
        # A tiny transparent 1x1 GIF base64 string
        payload["image_frame"] = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

    try:
        r = requests.post(url, json=payload, timeout=5)
        print(f"[{payload['timestamp']}] {sid:8s} {status:14s} → {r.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  ERROR: could not connect to {url}")


def main():
    parser = argparse.ArgumentParser(description="Mock heartbeat sender")
    parser.add_argument("--url", default="http://localhost:8000/api/heartbeat")
    parser.add_argument("--sensor-url", default="http://localhost:8000/api/sensor/heartbeat")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between rounds")
    args = parser.parse_args()

    print(f"Sending heartbeats to {args.url} and {args.sensor_url} every {args.interval}s  (Ctrl+C to stop)\n")
    while True:
        for machine in MACHINES:
            send_heartbeat(args.url, machine)
        for sensor in SENSORS:
            send_sensor_heartbeat(args.sensor_url, sensor)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
