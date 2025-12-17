"""
Pydantic schemas for FastAPI surveillance system
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    MAMA = "mama"


class CameraType(str, Enum):
    ADMIN = "admin"
    SPY = "spy"


class SabotageMode(str, Enum):
    NORMAL = "normal"
    PIXEL = "pixel"
    GRAY = "gray"
    FREEZE = "freeze"
    SLOW = "slow"
    STATIC = "static"


# User schemas
class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class UserInfo(BaseModel):
    username: str
    role: UserRole
    last_login: Optional[datetime] = None


# Camera schemas
class CameraBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    ip_url: str = Field(..., min_length=1, max_length=500)
    camera_type: CameraType = CameraType.ADMIN
    enabled: bool = True


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    ip_url: Optional[str] = None
    enabled: Optional[bool] = None


class Camera(CameraBase):
    id: str
    created_at: datetime
    is_active: bool = False
    person_detected: bool = False

    class Config:
        from_attributes = True


# Sabotage schemas
class SabotageControl(BaseModel):
    mode: SabotageMode
    target_camera: Optional[str] = None
    duration: Optional[int] = Field(None, ge=1, le=300)  # 1-300 seconds
    intensity: Optional[int] = Field(None, ge=1, le=10)  # 1-10 intensity
    auto_mode: bool = False


class SabotageStatus(BaseModel):
    current_mode: SabotageMode
    is_auto_running: bool = False
    is_preemptive_active: bool = False
    fps: Optional[int] = None
    target_camera: Optional[str] = None


# WebSocket schemas
class WebSocketMessage(BaseModel):
    event: str
    data: Dict[str, Any]
    room: Optional[str] = None


class PersonDetectionAlert(BaseModel):
    camera_id: str
    timestamp: datetime
    confidence: float
    bounding_box: Optional[Dict[str, float]] = None


class CameraStatusUpdate(BaseModel):
    camera_id: str
    is_active: bool
    person_detected: bool = False


class UserSessionUpdate(BaseModel):
    username: str
    action: str  # "login", "logout", "kicked"
    timestamp: datetime


# System status schemas
class SystemStatus(BaseModel):
    cameras: List[CameraStatusUpdate]
    sabotage_status: SabotageStatus
    mama_status: Dict[str, Any]
    connected_users: int
    mama_login_count: int


# Response schemas
class LoginResponse(BaseModel):
    message: str
    user: UserInfo
    redirect_url: str


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    error_code: Optional[str] = None