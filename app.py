"""
Digital Twin Dashboard – FastAPI backend
"""
import asyncio
import json
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Dict, List

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import requests

import store
from store import HeartbeatPayload, SensorHeartbeatPayload, SensorStatus, OFFLINE_THRESHOLD_SECONDS
from mock_data import seed
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="Factory Digital Twin API", version="1.0.0")
templates = Jinja2Templates(directory="templates")

N8N_WEBHOOK_URL = "https://2dd4-106-51-87-203.ngrok-free.app/webhook/522d8b55-afa6-47e4-9ffb-ab1597141c53/chat"

# SSE subscriber queues
_sse_subscribers: List[asyncio.Queue] = []


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    seed()
    asyncio.create_task(_offline_checker())


# ── Background: offline checker ───────────────────────────────────────────────

async def _offline_checker():
    """Every 30 s mark machines offline if heartbeat is overdue."""
    while True:
        await asyncio.sleep(30)
        now = datetime.now(timezone.utc)
        for mid, machine in store.machines.items():
            if machine["status"] == "offline":
                continue
            threshold = store.offline_thresholds.get(mid, OFFLINE_THRESHOLD_SECONDS)
            last_hb = datetime.fromisoformat(machine["last_heartbeat"])
            if last_hb.tzinfo is None:
                last_hb = last_hb.replace(tzinfo=timezone.utc)
            if (now - last_hb).total_seconds() > threshold:
                prev = machine["status"]
                machine["status"] = "offline"
                _add_alert(mid, prev, "offline")
                _broadcast({"event": "status_change", "machine_id": mid, "status": "offline"})


def _add_alert(machine_id: str, prev: str, current: str):
    name = store.machines[machine_id].get("name", machine_id)
    alert = {
        "machine_id": machine_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alert_type": "error_state" if current == "error" else "went_offline",
        "previous_status": prev,
        "current_status": current,
        "message": f"{name} transitioned from {prev} → {current}",
    }
    store.alerts.append(alert)
    _broadcast({"event": "alert", **alert})


def _broadcast(data: dict):
    msg = json.dumps(data)
    for q in list(_sse_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


# ── SSE ───────────────────────────────────────────────────────────────────────

@app.get("/events", tags=["Realtime"])
async def sse_stream(request: Request):
    """Server-Sent Events stream for real-time dashboard updates."""
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_subscribers.append(q)

    async def generator() -> AsyncGenerator[str, None]:
        # Send current snapshot on connect
        snapshot = json.dumps({"event": "snapshot", "machines": list(store.machines.values())})
        yield f"data: {snapshot}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"   # keep-alive
        finally:
            _sse_subscribers.remove(q)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Heartbeat API ─────────────────────────────────────────────────────────────

@app.post("/api/heartbeat", status_code=202, tags=["Heartbeat"],
          summary="Receive machine heartbeat",
          description="Accepts a heartbeat from a factory machine and updates its live state.")
async def receive_heartbeat(payload: HeartbeatPayload):
    """
    **Request body example:**
    ```json
    {
      "machine_id": "CNC-001",
      "timestamp": "2024-01-15T10:30:00Z",
      "status": "running",
      "health_metrics": {
        "temperature": 72.5,
        "vibration": 2.3,
        "power_consumption": 13.2
      },
      "metadata": {"operator": "John"}
    }
    ```
    """
    mid = payload.machine_id
    prev_status = store.machines.get(mid, {}).get("status")

    record = {
        "machine_id": mid,
        "timestamp": payload.timestamp.isoformat(),
        "status": payload.status,
        "health_metrics": payload.health_metrics.model_dump(),
        "metadata": payload.metadata,
    }

    # Update history
    if mid not in store.heartbeat_history:
        store.heartbeat_history[mid] = deque(maxlen=store.MAX_HISTORY)
    store.heartbeat_history[mid].append(record)

    # Update live state
    existing = store.machines.get(mid, {})
    store.machines[mid] = {
        "machine_id": mid,
        "name": (payload.metadata or {}).get("name", existing.get("name", mid)),
        "location": (payload.metadata or {}).get("location", existing.get("location", "Unknown")),
        "status": payload.status,
        "last_heartbeat": payload.timestamp.isoformat(),
        "health_metrics": payload.health_metrics.model_dump(),
        "metadata": payload.metadata,
    }

    # Alert on bad transitions
    if prev_status and prev_status != payload.status and payload.status in ("error", "offline"):
        _add_alert(mid, prev_status, payload.status)

    _broadcast({"event": "heartbeat", **record})
    return {"accepted": True, "machine_id": mid, "status": payload.status}


# ── Hardware / Notification Mock Functions ────────────────────────────────────

def trigger_hardware_alarm(sensor_id: str, status: str):
    logger.warning(f"HARDWARE ALARM ACTIVATED for sensor {sensor_id} due to {status}")

def send_notification(sensor_id: str, status: str, timestamp: str):
    email_template = f"ALERT: {status} detected by sensor {sensor_id} at {timestamp}"
    sms_template = f"Factory Alarm: {status} at {sensor_id}"
    logger.info(f"Sending Email: {email_template}")
    logger.info(f"Sending SMS: {sms_template}")


# ── Sensor Heartbeat API ──────────────────────────────────────────────────────
# This endpoint is for factory sensors (e.g. smoke, human presence) to report their status.
# Status Values: Normal, Smoke Detected, Human Detected
@app.post("/api/sensor/heartbeat", status_code=202, tags=["Heartbeat"],
          summary="Receive sensor heartbeat",
          description="Accepts a heartbeat from a factory sensor and triggers alarms if needed. Status Values: Normal, Smoke Detected, Human Detected, image_frame (base64 string of latest camera frame).")
async def receive_sensor_heartbeat(payload: SensorHeartbeatPayload):
    sid = payload.sensor_id
    status = payload.status

    if status in (SensorStatus.SMOKE_DETECTED, SensorStatus.HUMAN_DETECTED):
        alert = {
            "machine_id": sid,
            "timestamp": payload.timestamp.isoformat(),
            "alert_type": "sensor_alarm",
            "previous_status": "Normal",
            "current_status": status.value,
            "message": f"Sensor {sid} reported {status.value}"
        }
        if payload.image_frame:
            alert["image_frame"] = payload.image_frame
        
        store.alerts.append(alert)
        _broadcast({"event": "alert", **alert})

        send_notification(sid, status.value, payload.timestamp.isoformat())
        trigger_hardware_alarm(sid, status.value)

    return {"accepted": True, "sensor_id": sid, "status": status.value}


# ── Machine APIs ──────────────────────────────────────────────────────────────

@app.get("/api/machines", tags=["Machines"], summary="List all machines")
async def list_machines():
    """Returns current state of all known machines."""
    return list(store.machines.values())


@app.get("/api/machines/{machine_id}", tags=["Machines"], summary="Get single machine state")
async def get_machine(machine_id: str):
    if machine_id not in store.machines:
        raise HTTPException(404, f"Machine '{machine_id}' not found")
    return store.machines[machine_id]


@app.get("/api/machines/{machine_id}/history", tags=["Machines"],
         summary="Get heartbeat history for a machine")
async def get_history(machine_id: str, limit: int = 100):
    if machine_id not in store.heartbeat_history:
        raise HTTPException(404, f"No history for '{machine_id}'")
    history = list(store.heartbeat_history[machine_id])
    return {"machine_id": machine_id, "count": len(history), "records": history[-limit:]}


# ── Alerts API ────────────────────────────────────────────────────────────────

@app.get("/api/alerts", tags=["Alerts"], summary="List recent alerts")
async def list_alerts(limit: int = 50):
    """Returns the most recent alerts (error/offline transitions)."""
    alerts = list(store.alerts)
    return {"count": len(alerts), "alerts": alerts[-limit:]}


# ── Config API ────────────────────────────────────────────────────────────────

@app.put("/api/config/threshold/{machine_id}", tags=["Config"],
         summary="Set offline threshold for a machine")
async def set_threshold(machine_id: str, seconds: int):
    """
    Override the offline detection threshold for a specific machine.
    - **seconds**: heartbeat timeout in seconds (min 10)
    """
    if seconds < 10:
        raise HTTPException(400, "Threshold must be at least 10 seconds")
    store.offline_thresholds[machine_id] = seconds
    return {"machine_id": machine_id, "threshold_seconds": seconds}


@app.get("/api/config/threshold", tags=["Config"], summary="Get all threshold configs")
async def get_thresholds():
    return {
        "default_threshold_seconds": OFFLINE_THRESHOLD_SECONDS,
        "overrides": store.offline_thresholds,
    }


# ── Analytics API ─────────────────────────────────────────────────────────────

@app.get("/api/analytics/{machine_id}", tags=["Analytics"],
         summary="Get analytics for a machine")
async def get_analytics(machine_id: str, hours: int = 24):
    if machine_id not in store.heartbeat_history:
        raise HTTPException(404, f"No data for '{machine_id}'")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    records = [
        r for r in store.heartbeat_history[machine_id]
        if datetime.fromisoformat(r["timestamp"]).replace(tzinfo=timezone.utc) >= cutoff
    ]

    if not records:
        return {"machine_id": machine_id, "hours": hours, "message": "No data in range"}

    status_counts: Dict[str, int] = {}
    for r in records:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    total = len(records)
    uptime_pct = round((status_counts.get("running", 0) / total) * 100, 1)
    error_pct  = round((status_counts.get("error", 0)   / total) * 100, 1)

    # Avg metrics (running only)
    running = [r for r in records if r["status"] == "running"]
    avg_metrics = {}
    if running:
        for key in ("temperature", "vibration", "power_consumption"):
            vals = [r["health_metrics"][key] for r in running if r["health_metrics"].get(key) is not None]
            avg_metrics[key] = round(sum(vals) / len(vals), 2) if vals else None

    return {
        "machine_id": machine_id,
        "hours_analyzed": hours,
        "total_records": total,
        "uptime_percentage": uptime_pct,
        "error_percentage": error_pct,
        "status_distribution": status_counts,
        "avg_metrics_while_running": avg_metrics,
    }


@app.get("/api/analytics", tags=["Analytics"], summary="Fleet-wide analytics summary")
async def fleet_analytics(hours: int = 24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    fleet: dict = {}
    for mid in store.heartbeat_history:
        records = [
            r for r in store.heartbeat_history[mid]
            if datetime.fromisoformat(r["timestamp"]).replace(tzinfo=timezone.utc) >= cutoff
        ]
        if not records:
            continue
        total = len(records)
        running = sum(1 for r in records if r["status"] == "running")
        errors  = sum(1 for r in records if r["status"] == "error")
        fleet[mid] = {
            "uptime_pct": round(running / total * 100, 1),
            "error_pct":  round(errors  / total * 100, 1),
            "total_records": total,
        }
    return {"hours_analyzed": hours, "fleet": fleet}


# ── Chat Proxy ────────────────────────────────────────────────────────────

@app.post("/api/chat", tags=["Chat"], summary="Proxy chat to n8n")
async def chat_proxy(request: Request):
    """Forward chat messages to the n8n webhook and stream NDJSON back."""
    body = await request.json()
    payload = {
        "sessionId": body.get("sessionId", ""),
        "action": "sendMessage",
        "chatInput": body.get("chatInput", ""),
    }

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _fetch():
        """Run blocking requests.post in a thread, push chunks to queue."""
        try:
            resp = requests.post(
                N8N_WEBHOOK_URL, json=payload, stream=True, timeout=(10, 300)
            )
            for chunk in resp.iter_content(chunk_size=None):
                if chunk:
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except requests.ConnectionError:
            err = json.dumps({"error": "Cannot reach chat backend"}).encode() + b"\n"
            loop.call_soon_threadsafe(queue.put_nowait, err)
        except requests.Timeout:
            err = json.dumps({"error": "Chat backend timed out"}).encode() + b"\n"
            loop.call_soon_threadsafe(queue.put_nowait, err)
        except Exception:
            err = json.dumps({"error": "Chat backend error"}).encode() + b"\n"
            loop.call_soon_threadsafe(queue.put_nowait, err)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    async def generate():
        asyncio.get_event_loop().run_in_executor(None, _fetch)
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# ── UI Routes ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/analytics", response_class=HTMLResponse, include_in_schema=False)
async def analytics_page(request: Request):
    return templates.TemplateResponse("analytics.html", {"request": request})


@app.get("/shopfloor", response_class=HTMLResponse, include_in_schema=False)
async def shopfloor_page(request: Request):
    return templates.TemplateResponse("shopfloor.html", {"request": request})
