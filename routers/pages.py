"""
Main page routes for FastAPI surveillance system
"""
import time
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from utils.auth import get_current_user_from_session, require_auth, require_admin
from services.camera_service import camera_manager
from utils.video_processing import sabotage_engine

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
async def root(request: Request):
    """Root endpoint - redirect to appropriate page"""
    try:
        # Try to get current user
        session_id = request.cookies.get("session_id")
        if not session_id:
            return RedirectResponse(url="/login", status_code=302)
        
        # Get user from session
        from utils.auth import session_manager
        user = session_manager.get_session(session_id)
        
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        
        # Redirect based on role
        if user["role"] == "admin":
            return RedirectResponse(url="/admin", status_code=302)
        else:
            return RedirectResponse(url="/dashboard", status_code=302)
    
    except Exception:
        return RedirectResponse(url="/login", status_code=302)


@router.get("/dashboard")
async def dashboard(request: Request, current_user: dict = Depends(get_current_user_from_session)):
    """Main dashboard for mama users"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get session_id from cookies
    session_id = request.cookies.get("session_id", "")
    
    # Get camera list
    cameras = camera_manager.get_camera_list()
    
    # Filter cameras based on user role and mama camera access
    if current_user["role"] != "admin":
        # Check if mama camera is enabled
        mama_camera_enabled = camera_manager.is_mama_camera_enabled()
        if not mama_camera_enabled:
            # Filter out spy cameras
            cameras = [cam for cam in cameras if cam["type"] != "spy"]
    
    # Get sabotage status
    sabotage_status = {
        "current_mode": sabotage_engine.current_mode.value,
        "enabled": sabotage_engine.enabled,
        "available_modes": [mode.value for mode in sabotage_engine.available_modes]
    }
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": current_user,
            "rol": current_user.get("role", "mama"),
            "session": {"session_id": session_id},
            "cameras": cameras,
            "sabotage_status": sabotage_status,
            "mama_camera_enabled": camera_manager.is_mama_camera_enabled(),
            "timestamp": int(time.time())
        }
    )


@router.get("/admin")
async def admin_panel(request: Request, current_user: dict = Depends(require_admin)):
    """Admin panel"""
    # Get session_id from cookies
    session_id = request.cookies.get("session_id", "")
    
    # Get camera list
    cameras = camera_manager.get_camera_list()
    
    # Get sabotage status
    sabotage_status = {
        "current_mode": sabotage_engine.current_mode.value,
        "enabled": sabotage_engine.enabled,
        "available_modes": [mode.value for mode in sabotage_engine.available_modes]
    }
    
    # Get session information
    from utils.auth import session_manager
    active_sessions = session_manager.get_all_sessions()
    
    # Get system statistics
    from services.websocket_service import connection_manager
    websocket_stats = connection_manager.get_stats()
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": current_user,
            "session": {"session_id": session_id},
            "rol": current_user.get("role", "admin"),
            "cameras": cameras,
            "sabotage_status": sabotage_status,
            "active_sessions": active_sessions,
            "websocket_stats": websocket_stats,
            "mama_camera_enabled": camera_manager.is_mama_camera_enabled(),
            "timestamp": int(time.time())
        }
    )


@router.get("/camera/{camera_id}")
async def camera_view(
    camera_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_from_session)
):
    """Individual camera view"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get session_id from cookies
    session_id = request.cookies.get("session_id", "")
    
    # Get camera info
    cameras = camera_manager.get_camera_list()
    camera = next((cam for cam in cameras if cam["id"] == camera_id), None)
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check access permissions
    if current_user["role"] != "admin":
        # Check if mama can access this camera
        if camera["type"] == "spy" and not camera_manager.is_mama_camera_enabled():
            raise HTTPException(status_code=403, detail="Camera access disabled")
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": current_user,
            "rol": current_user.get("role", "mama"),
            "session": {"session_id": session_id},
            "camera": camera,
            "mama_camera_enabled": camera_manager.is_mama_camera_enabled(),
            "timestamp": int(time.time())
        }
    )


@router.get("/settings")
async def settings_page(request: Request, current_user: dict = Depends(require_admin)):
    """Settings page (admin only)"""
    # Get current configuration
    from models.config import settings as app_settings
    
    config_info = {
        "yolo_model": app_settings.yolo_model_path,
        "max_queue_size": app_settings.max_queue_size,
        "connection_timeout": app_settings.connection_timeout,
        "read_timeout": app_settings.read_timeout,
        "sound_cooldown": app_settings.sound_cooldown,
        "session_timeout": app_settings.session_timeout
    }
    
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": current_user,
            "config": config_info
        }
    )


@router.get("/help")
async def help_page(request: Request, current_user: dict = Depends(get_current_user_from_session)):
    """Help and documentation page"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "help.html",
        {
            "request": request,
            "user": current_user
        }
    )


@router.get("/test")
async def test_websocket_page(request: Request):
    """Test WebSocket page - no authentication required"""
    return templates.TemplateResponse(
        "test_websocket.html",
        {
            "request": request
        }
    )


@router.get("/status")
async def status_page(request: Request, current_user: dict = Depends(require_admin)):
    """System status page (admin only)"""
    # Get comprehensive system status
    camera_stats = {
        "total_cameras": len(camera_manager.cameras),
        "active_cameras": sum(1 for active in camera_manager.camera_active.values() if active),
        "cameras_with_detection": sum(1 for detected in camera_manager.person_detected.values() if detected)
    }
    
    from services.websocket_service import connection_manager
    websocket_stats = connection_manager.get_stats()
    
    from utils.auth import session_manager
    session_stats = {
        "total_sessions": len(session_manager.sessions),
        "admin_sessions": len([s for s in session_manager.sessions.values() if s["role"] == "admin"]),
        "mama_sessions": len([s for s in session_manager.sessions.values() if s["role"] == "mama"])
    }
    
    from services.audio_service import audio_manager
    audio_stats = audio_manager.get_sound_info()
    
    system_status = {
        "cameras": camera_stats,
        "websockets": websocket_stats,
        "sessions": session_stats,
        "audio": audio_stats,
        "sabotage": {
            "enabled": sabotage_engine.enabled,
            "current_mode": sabotage_engine.current_mode.value
        }
    }
    
    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "user": current_user,
            "system_status": system_status
        }
    )