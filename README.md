# Factory Digital Twin Dashboard

A real-time digital twin system for monitoring factory machines via heartbeat API.

## Quick Start

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open **http://localhost:8000** for the dashboard, **http://localhost:8000/analytics** for analytics,
and **http://localhost:8000/docs** for the interactive Swagger UI.

---

## Architecture

```
app.py          – FastAPI application (routes, SSE, background tasks)
store.py        – In-memory data models and shared state
mock_data.py    – Seeds 48 h of realistic heartbeat history on startup
templates/
  dashboard.html  – Real-time machine status dashboard (SSE-driven)
  analytics.html  – Uptime / error-rate analytics view
```

---

## API Reference

### POST `/api/heartbeat`
Receive a heartbeat from a machine.

**Request body:**
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
  "metadata": {
    "name": "CNC Lathe Alpha",
    "location": "Floor A",
    "operator": "Jane Smith"
  }
}
```

**Status values:** `running` | `idle` | `error` | `offline`

**Response `202`:**
```json
{ "accepted": true, "machine_id": "CNC-001", "status": "running" }
```

---

### GET `/api/machines`
Returns current state of all known machines.

**Response:**
```json
[
  {
    "machine_id": "CNC-001",
    "name": "CNC Lathe Alpha",
    "location": "Floor A",
    "status": "running",
    "last_heartbeat": "2024-01-15T10:30:00+00:00",
    "health_metrics": { "temperature": 72.5, "vibration": 2.3, "power_consumption": 13.2 },
    "metadata": {}
  }
]
```

---

### GET `/api/machines/{machine_id}`
Returns current state of a single machine.

---

### GET `/api/machines/{machine_id}/history?limit=100`
Returns the last N heartbeat records for a machine.

**Response:**
```json
{
  "machine_id": "CNC-001",
  "count": 100,
  "records": [
    { "machine_id": "CNC-001", "timestamp": "...", "status": "running", "health_metrics": {...}, "metadata": {} }
  ]
}
```

---

### GET `/api/alerts?limit=50`
Returns the most recent alert events (error/offline transitions).

**Response:**
```json
{
  "count": 5,
  "alerts": [
    {
      "machine_id": "WLD-002",
      "timestamp": "2024-01-15T09:15:00+00:00",
      "alert_type": "error_state",
      "previous_status": "running",
      "current_status": "error",
      "message": "Welding Robot 2 transitioned from running → error"
    }
  ]
}
```

**Alert types:** `error_state` | `went_offline`

---

### GET `/api/analytics/{machine_id}?hours=24`
Per-machine analytics over the specified time window.

**Response:**
```json
{
  "machine_id": "CNC-001",
  "hours_analyzed": 24,
  "total_records": 288,
  "uptime_percentage": 82.3,
  "error_percentage": 4.5,
  "status_distribution": { "running": 237, "idle": 38, "error": 13 },
  "avg_metrics_while_running": {
    "temperature": 69.4,
    "vibration": 2.1,
    "power_consumption": 12.3
  }
}
```

---

### GET `/api/analytics?hours=24`
Fleet-wide analytics summary.

**Response:**
```json
{
  "hours_analyzed": 24,
  "fleet": {
    "CNC-001": { "uptime_pct": 82.3, "error_pct": 4.5, "total_records": 288 },
    "WLD-002": { "uptime_pct": 61.0, "error_pct": 18.2, "total_records": 288 }
  }
}
```

---

### PUT `/api/config/threshold/{machine_id}?seconds=300`
Override the offline detection threshold for a specific machine.

- **seconds** (query param): timeout in seconds before marking offline (min 10, default 300)

**Response:**
```json
{ "machine_id": "CNC-001", "threshold_seconds": 120 }
```

---

### GET `/api/config/threshold`
Returns the global default and all per-machine overrides.

**Response:**
```json
{
  "default_threshold_seconds": 300,
  "overrides": { "CNC-001": 120 }
}
```

---

### GET `/events`
Server-Sent Events stream for real-time dashboard updates.

**Event types:**
| Event | Description |
|---|---|
| `snapshot` | Full machine list sent on connect |
| `heartbeat` | New heartbeat received |
| `status_change` | Machine marked offline by background checker |
| `alert` | Error/offline transition alert |

---

## Offline Detection

The background task runs every **30 seconds** and marks any machine as `offline`
if its last heartbeat is older than the configured threshold (default **5 minutes**).

Override per machine:
```
PUT /api/config/threshold/CNC-001?seconds=120
```

---

## Mock Data

On startup, `mock_data.py` seeds **8 machines** with **48 hours** of heartbeat history
(one record every 5 minutes = ~576 records per machine). Current statuses:

| Machine | Status |
|---|---|
| CNC-001 | running |
| CNC-002 | idle |
| WLD-001 | running |
| WLD-002 | error |
| PRS-001 | running |
| CNV-001 | running |
| CMR-001 | idle |
| ASM-001 | offline |
