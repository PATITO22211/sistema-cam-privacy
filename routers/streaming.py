"""
Video streaming routes for FastAPI surveillance system
"""
import asyncio
import queue
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import Generator

from utils.auth import get_current_user_from_session
from services.camera_service import camera_manager
from utils.video_processing import VideoProcessor
from models.config import settings

router = APIRouter(prefix="/api/stream", tags=["streaming"])


def generate_frames(camera_id: str, is_admin: bool = True) -> Generator[bytes, None, None]:
    """Generate video frames for streaming"""
    frame_queue = camera_manager.get_frame_queue(camera_id, is_admin)
    
    if not frame_queue:
        return
    
    while True:
        try:
            # Get frame from queue with timeout
            frame = frame_queue.get(timeout=1.0)

            # Encode frame to JPEG
            encoded_frame = VideoProcessor.encode_frame_to_jpeg(frame, quality=settings.stream_jpeg_quality)
            
            # Yield frame in multipart format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + encoded_frame + b'\r\n')
        
        except queue.Empty:
            # No frame available, continue
            continue
        except Exception as e:
            print(f"Error in frame generation for camera {camera_id}: {e}")
            break


@router.get("/{camera_id}")
async def stream_camera(
    camera_id: str,
    current_user: dict = Depends(get_current_user_from_session)
):
    """Stream video from a specific camera"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Check if camera exists
    if camera_id not in camera_manager.cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    camera_info = camera_manager.cameras[camera_id]
    is_admin = current_user["role"] == "admin"
    
    # Check access permissions
    if not is_admin:
        # Check if mama can access this camera
        if camera_info["type"] == "spy" and not camera_manager.is_mama_camera_enabled():
            raise HTTPException(status_code=403, detail="Camera access disabled")
    
    # Check if camera is active
    if not camera_manager.camera_active.get(camera_id, False):
        raise HTTPException(status_code=503, detail="Camera is not active")
    
    return StreamingResponse(
        generate_frames(camera_id, is_admin),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/{camera_id}/snapshot")
async def get_camera_snapshot(
    camera_id: str,
    current_user: dict = Depends(get_current_user_from_session)
):
    """Get a single snapshot from a camera"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Check if camera exists
    if camera_id not in camera_manager.cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    camera_info = camera_manager.cameras[camera_id]
    is_admin = current_user["role"] == "admin"
    
    # Check access permissions
    if not is_admin:
        if camera_info["type"] == "spy" and not camera_manager.is_mama_camera_enabled():
            raise HTTPException(status_code=403, detail="Camera access disabled")
    
    # Check if camera is active
    if not camera_manager.camera_active.get(camera_id, False):
        raise HTTPException(status_code=503, detail="Camera is not active")
    
    # Get frame queue
    frame_queue = camera_manager.get_frame_queue(camera_id, is_admin)
    
    if not frame_queue:
        raise HTTPException(status_code=503, detail="Camera feed not available")
    
    try:
        # Get latest frame
        frame = frame_queue.get(timeout=2.0)
        
        # Encode frame to JPEG
        encoded_frame = VideoProcessor.encode_frame_to_jpeg(frame, quality=95)
        
        return StreamingResponse(
            iter([encoded_frame]),
            media_type="image/jpeg"
        )
    
    except queue.Empty:
        raise HTTPException(status_code=503, detail="No frame available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting snapshot: {str(e)}")


@router.get("/")
async def list_available_streams(current_user: dict = Depends(get_current_user_from_session)):
    """List available camera streams"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    cameras = camera_manager.get_camera_list()
    is_admin = current_user["role"] == "admin"
    
    # Filter cameras based on user role
    available_streams = []
    for camera in cameras:
        # Check access permissions
        if not is_admin:
            if camera["type"] == "spy" and not camera_manager.is_mama_camera_enabled():
                continue
        
        available_streams.append({
            "camera_id": camera["id"],
            "name": camera["name"],
            "type": camera["type"],
            "is_active": camera["is_active"],
            "stream_url": f"/api/stream/{camera['id']}",
            "snapshot_url": f"/api/stream/{camera['id']}/snapshot"
        })
    
    return {
        "streams": available_streams,
        "total": len(available_streams),
        "user_role": current_user["role"]
    }


@router.get("/status/{camera_id}")
async def get_stream_status(
    camera_id: str,
    current_user: dict = Depends(get_current_user_from_session)
):
    """Get streaming status for a specific camera"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Check if camera exists
    if camera_id not in camera_manager.cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    camera_info = camera_manager.cameras[camera_id]
    is_admin = current_user["role"] == "admin"
    
    # Check access permissions
    if not is_admin:
        if camera_info["type"] == "spy" and not camera_manager.is_mama_camera_enabled():
            raise HTTPException(status_code=403, detail="Camera access disabled")
    
    # Get frame queue
    frame_queue = camera_manager.get_frame_queue(camera_id, is_admin)
    
    return {
        "camera_id": camera_id,
        "name": camera_info["name"],
        "type": camera_info["type"],
        "is_active": camera_manager.camera_active.get(camera_id, False),
        "queue_size": frame_queue.qsize() if frame_queue else 0,
        "person_detected": camera_manager.person_detected.get(camera_id, False),
        "accessible": frame_queue is not None
    }
