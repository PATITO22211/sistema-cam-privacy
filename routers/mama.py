"""
Mama management routes for FastAPI surveillance system
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from models.schemas import ApiResponse
from utils.auth import require_auth, require_admin
from services.camera_service import camera_manager
from services.websocket_service import connection_manager

router = APIRouter(prefix="/api/mama", tags=["mama"])


class MamaCameraToggle(BaseModel):
    enabled: bool


@router.get("/status")
async def get_mama_status(current_user: dict = Depends(require_auth)):
    """Get mama status for frontend"""
    return {
        "enabled": camera_manager.is_mama_camera_enabled(),
        "connected": len(connection_manager.mama_connections) > 0,
        "status": "active" if camera_manager.is_mama_camera_enabled() else "inactive"
    }


@router.post("/camera", response_model=ApiResponse)
async def toggle_mama_camera_api(
    request_data: MamaCameraToggle,
    current_user: dict = Depends(require_admin)
):
    """Toggle mama camera access via API"""
    try:
        enabled = request_data.enabled
        
        # Set the new state directly
        camera_manager.set_mama_camera_enabled(enabled)
        
        # Send WebSocket notification (fix: use broadcast_to_admins)
        await connection_manager.broadcast_to_admins({
            "type": "mama_camera_toggle",
            "enabled": enabled,
            "message": f"Mama camera access {'enabled' if enabled else 'disabled'}"
        })
        
        return {
            "success": True,
            "message": f"Mama camera access {'enabled' if enabled else 'disabled'}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle mama camera: {str(e)}")