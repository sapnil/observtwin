from collections import deque
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from enum import Enum
import base64
from typing import Dict, Optional
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


class SensorStatus(str, Enum):
    NORMAL = "Normal"
    SMOKE_DETECTED = "Smoke Detected"
    HUMAN_DETECTED = "Human Detected"


class SensorHeartbeatPayload(BaseModel):
    sensor_id: str = Field(..., min_length=1)
    timestamp: datetime
    status: SensorStatus
    image_frame: Optional[str] = None

    @field_validator("image_frame")
    @classmethod
    def validate_image_frame(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if len(v) > 5 * 1024 * 1024: # 5MB limit
                raise ValueError("Image frame base64 string exceeds size limit")
            try:
                # Basic validation for base64
                base64.b64decode(v)
            except Exception:
                raise ValueError("Invalid base64 string")
        return v


class Alert(BaseModel):
    machine_id: str
    timestamp: datetime
    alert_type: str   # "error_state" | "went_offline"
    previous_status: str
    current_status: str
    message: str


# ── In-memory stores ──────────────────────────────────────────────────────────

# Latest state per machine
machines: Dict[str, dict] = {}

# Heartbeat history per machine  {machine_id: deque of dicts}
heartbeat_history: Dict[str, deque] = {}

# Global alert log
alerts: deque = deque(maxlen=200)

# Per-machine offline threshold override (seconds)
offline_thresholds: Dict[str, int] = {}
