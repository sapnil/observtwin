from collections import deque
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


MAX_HISTORY = 500  # max heartbeat records per machine
OFFLINE_THRESHOLD_SECONDS = 300  # 5 minutes default


class HealthMetrics(BaseModel):
    temperature: Optional[float] = None   # Celsius
    vibration: Optional[float] = None     # mm/s
    power_consumption: Optional[float] = None  # kW


class HeartbeatPayload(BaseModel):
    machine_id: str
    timestamp: datetime
    status: str = Field(..., pattern="^(running|anomaly|error|offline)$")
    health_metrics: HealthMetrics = HealthMetrics()
    metadata: Optional[dict] = None


class Alert(BaseModel):
    machine_id: str
    timestamp: datetime
    alert_type: str   # "error_state" | "went_offline"
    previous_status: str
    current_status: str
    message: str


# ── In-memory stores ──────────────────────────────────────────────────────────

# Latest state per machine
machines: dict[str, dict] = {}

# Heartbeat history per machine  {machine_id: deque of dicts}
heartbeat_history: dict[str, deque] = {}

# Global alert log
alerts: deque = deque(maxlen=200)

# Per-machine offline threshold override (seconds)
offline_thresholds: dict[str, int] = {}
