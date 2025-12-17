"""
Camera management routes for FastAPI surveillance system
"""
import time
from fastapi import APIRouter, HTTPException, Depends, Form
from typing import List, Optional

from models.schemas import (
    Camera, CameraCreate, CameraUpdate, CameraType,
    ApiResponse, SystemStatus
)
from utils.auth import require_auth, require_admin
from services.camera_service import camera_manager
from services.websocket_service import connection_manager

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("/", response_model=List[Camera])
async def get_cameras(current_user: dict = Depends(require_auth)):
    """Get list of all cameras"""
    cameras = camera_manager.get_camera_list()
    
    # Filter cameras based on user role
    if current_user["role"] != "admin":
        # Check if mama can access spy cameras
        if not camera_manager.is_mama_camera_enabled():
            cameras = [cam for cam in cameras if cam["type"] != "spy"]
    
    return cameras


@router.get("/{camera_id}", response_model=Camera)
async def get_camera(camera_id: str, current_user: dict = Depends(require_auth)):
    """Get specific camera information"""
    cameras = camera_manager.get_camera_list()
    camera = next((cam for cam in cameras if cam["id"] == camera_id), None)
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check access permissions
    if current_user["role"] != "admin":
        if camera["type"] == "spy" and not camera_manager.is_mama_camera_enabled():
            raise HTTPException(status_code=403, detail="Camera access disabled")
    
    return camera


@router.post("/", response_model=ApiResponse)
async def create_camera(
    camera_data: CameraCreate,
    current_user: dict = Depends(require_admin)
):
    """Create a new camera (admin only)"""
    try:
        # Generate camera ID
        camera_id = f"custom_{len(camera_manager.cameras)}"
        
        # Add camera
        camera_manager.add_camera(
            camera_id=camera_id,
            name=camera_data.name,
            ip_url=camera_data.ip_url,
            camera_type=camera_data.type
        )
        
        # Start camera if enabled
        if camera_data.enabled:
            camera_manager.start_camera(camera_id)
        
        # Notify via WebSocket
        await connection_manager.send_camera_status_update(
            camera_id=camera_id,
            is_active=camera_manager.camera_active.get(camera_id, False),
            person_detected=camera_manager.person_detected.get(camera_id, False)
        )
        
        return ApiResponse(
            success=True,
            message=f"Camera '{camera_data.name}' created successfully",
            data={"camera_id": camera_id}
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create camera: {str(e)}")


@router.put("/{camera_id}", response_model=ApiResponse)
async def update_camera(
    camera_id: str,
    camera_data: CameraUpdate,
    current_user: dict = Depends(require_admin)
):
    """Update camera configuration (admin only)"""
    if camera_id not in camera_manager.cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    try:
        # Update camera info
        camera_info = camera_manager.cameras[camera_id]
        
        if camera_data.name is not None:
            camera_info["name"] = camera_data.name
        
        if camera_data.ip_url is not None:
            camera_info["ip_url"] = camera_data.ip_url
            # Restart camera to apply new URL
            camera_manager.stop_camera(camera_id)
            if camera_data.enabled is not False:
                camera_manager.start_camera(camera_id)
        
        if camera_data.enabled is not None:
            if camera_data.enabled:
                camera_manager.start_camera(camera_id)
            else:
                camera_manager.stop_camera(camera_id)
        
        # Notify via WebSocket
        await connection_manager.send_camera_status_update(
            camera_id=camera_id,
            is_active=camera_manager.camera_active.get(camera_id, False),
            person_detected=camera_manager.person_detected.get(camera_id, False)
        )
        
        return ApiResponse(
            success=True,
            message=f"Camera '{camera_id}' updated successfully"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update camera: {str(e)}")


@router.delete("/{camera_id}", response_model=ApiResponse)
async def delete_camera(
    camera_id: str,
    current_user: dict = Depends(require_admin)
):
    """Delete a camera (admin only)"""
    if camera_id not in camera_manager.cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Prevent deletion of default cameras
    if camera_id.startswith("admin_") or camera_id == "spy":
        raise HTTPException(status_code=400, detail="Cannot delete default cameras")
    
    try:
        camera_name = camera_manager.cameras[camera_id]["name"]
        
        # Remove camera
        success = camera_manager.remove_camera(camera_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to remove camera")
        
        # Notify via WebSocket
        await connection_manager.send_camera_status_update(
            camera_id=camera_id,
            is_active=False,
            person_detected=False
        )
        
        return ApiResponse(
            success=True,
            message=f"Camera '{camera_name}' deleted successfully"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete camera: {str(e)}")


@router.post("/{camera_id}/start", response_model=ApiResponse)
async def start_camera(
    camera_id: str,
    current_user: dict = Depends(require_admin)
):
    """Start a camera (admin only)"""
    print(f"Attempting to start camera: {camera_id}")
    
    if camera_id not in camera_manager.cameras:
        print(f"Camera {camera_id} not found in camera_manager.cameras")
        raise HTTPException(status_code=404, detail="Camera not found")
    
    try:
        print(f"Calling camera_manager.start_camera for {camera_id}")
        success = camera_manager.start_camera(camera_id)
        print(f"start_camera returned: {success}")
        
        if not success:
            print(f"Failed to start camera {camera_id}")
            raise HTTPException(status_code=500, detail="Failed to start camera")
        
        # Notify via WebSocket
        print(f"Sending WebSocket notification for camera {camera_id}")
        await connection_manager.send_camera_status_update(
            camera_id=camera_id,
            is_active=True,
            person_detected=camera_manager.person_detected.get(camera_id, False)
        )
        
        print(f"Camera {camera_id} started successfully")
        return ApiResponse(
            success=True,
            message=f"Camera '{camera_id}' started successfully"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Exception in start_camera for {camera_id}: {str(e)}")
        print(f"Full traceback: {error_details}")
        raise HTTPException(status_code=500, detail=f"Failed to start camera: {str(e)}")


@router.post("/{camera_id}/stop", response_model=ApiResponse)
async def stop_camera(
    camera_id: str,
    current_user: dict = Depends(require_admin)
):
    """Stop a camera (admin only)"""
    if camera_id not in camera_manager.cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    try:
        success = camera_manager.stop_camera(camera_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to stop camera")
        
        # Notify via WebSocket
        await connection_manager.send_camera_status_update(
            camera_id=camera_id,
            is_active=False,
            person_detected=camera_manager.person_detected.get(camera_id, False)
        )
        
        return ApiResponse(
            success=True,
            message=f"Camera '{camera_id}' stopped successfully"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop camera: {str(e)}")


@router.post("/start-all", response_model=ApiResponse)
async def start_all_cameras(current_user: dict = Depends(require_admin)):
    """Start all cameras (admin only)"""
    try:
        camera_manager.start_all_cameras()
        
        # Notify via WebSocket
        await connection_manager.send_camera_status_update(
            camera_id="all",
            is_active=True,
            person_detected=False
        )
        
        return ApiResponse(
            success=True,
            message="All cameras started successfully"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start cameras: {str(e)}")


@router.post("/stop-all", response_model=ApiResponse)
async def stop_all_cameras(current_user: dict = Depends(require_admin)):
    """Stop all cameras (admin only)"""
    try:
        camera_manager.stop_all_cameras()
        
        # Notify via WebSocket
        await connection_manager.send_camera_status_update(
            camera_id="all",
            is_active=False,
            person_detected=False
        )
        
        return ApiResponse(
            success=True,
            message="All cameras stopped successfully"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop cameras: {str(e)}")


@router.post("/mama-camera/toggle", response_model=ApiResponse)
async def toggle_mama_camera(current_user: dict = Depends(require_admin)):
    """Toggle mama's camera access (admin only)"""
    try:
        current_state = camera_manager.is_mama_camera_enabled()
        new_state = not current_state
        
        camera_manager.set_mama_camera_enabled(new_state)
        
        # Notify via WebSocket
        await connection_manager.send_high_priority_alert(
            alert_type="mama_camera_toggle",
            message_text=f"Mama camera access {'enabled' if new_state else 'disabled'}",
            data={"enabled": new_state}
        )
        
        return ApiResponse(
            success=True,
            message=f"Mama camera access {'enabled' if new_state else 'disabled'}",
            data={"enabled": new_state}
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle mama camera: {str(e)}")


@router.get("/mama-camera/status")
async def get_mama_camera_status(current_user: dict = Depends(require_auth)):
    """Get mama camera access status"""
    return {
        "enabled": camera_manager.is_mama_camera_enabled()
    }


# API endpoints for mama panel (matching frontend expectations)
@router.get("/mama/status")
async def get_mama_status(current_user: dict = Depends(require_auth)):
    """Get mama status for frontend"""
    return {
        "enabled": camera_manager.is_mama_camera_enabled(),
        "status": "active" if camera_manager.is_mama_camera_enabled() else "inactive"
    }


@router.post("/mama/camera")
async def toggle_mama_camera_api(current_user: dict = Depends(require_admin)):
    """Toggle mama camera access via API"""
    try:
        current_state = camera_manager.is_mama_camera_enabled()
        new_state = not current_state
        
        camera_manager.set_mama_camera_enabled(new_state)
        
        # Notify via WebSocket
        await connection_manager.send_high_priority_alert(
            alert_type="mama_camera_toggle",
            message_text=f"Mama camera access {'enabled' if new_state else 'disabled'}",
            data={"enabled": new_state}
        )
        
        return {
            "success": True,
            "enabled": new_state,
            "message": f"Mama camera access {'enabled' if new_state else 'disabled'}"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle mama camera: {str(e)}")


@router.post("/add-ip-camera", response_model=ApiResponse)
async def add_ip_camera(
    name: str = Form(...),
    ip_url: str = Form(...),
    camera_type: str = Form(default="admin"),
    current_user: dict = Depends(require_admin)
):
    """Add IP camera via form (admin only)"""
    try:
        # Validate camera type
        try:
            cam_type = CameraType(camera_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid camera type")
        
        # Generate camera ID
        camera_id = f"ip_{len([c for c in camera_manager.cameras if c.startswith('ip_')])}"
        
        # Add camera
        camera_manager.add_camera(
            camera_id=camera_id,
            name=name,
            ip_url=ip_url,
            camera_type=cam_type
        )
        
        # Start camera
        camera_manager.start_camera(camera_id)
        
        # Notify via WebSocket
        await connection_manager.send_camera_status_update(
            camera_id=camera_id,
            is_active=camera_manager.camera_active.get(camera_id, False),
            person_detected=camera_manager.person_detected.get(camera_id, False)
        )
        
        return ApiResponse(
            success=True,
            message=f"IP Camera '{name}' added successfully",
            data={"camera_id": camera_id}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add IP camera: {str(e)}")


@router.get("/system-status", response_model=SystemStatus)
async def get_system_status(current_user: dict = Depends(require_auth)):
    """Get system status"""
    cameras = camera_manager.get_camera_list()
    
    return SystemStatus(
        total_cameras=len(cameras),
        active_cameras=sum(1 for cam in cameras if cam["is_active"]),
        cameras_with_detection=sum(1 for cam in cameras if cam["person_detected"]),
        mama_camera_enabled=camera_manager.is_mama_camera_enabled(),
        timestamp=time.time()
    )