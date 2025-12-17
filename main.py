"""
FastAPI Surveillance System - Main Application
"""
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from routers import auth, pages, cameras, sabotage, streaming, websockets, mama

# Import services
from services.camera_service import camera_manager
from services.websocket_service import connection_manager
from services.audio_service import audio_manager

# Import models and config
from models.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    print("🚀 Starting FastAPI Surveillance System...")
    
    # Initialize services
    print("📹 Initializing camera manager...")
    # Capture and provide the running event loop to camera manager
    loop = asyncio.get_running_loop()
    camera_manager.set_event_loop(loop)
    
    # Setup detection callbacks
    camera_manager.add_detection_callback(handle_person_detection)
    camera_manager.add_status_callback(handle_camera_status)
    
    # Start all cameras
    print("🎥 Starting cameras...")
    camera_manager.start_all_cameras()

    camera_manager.start_recording("spy")
    
    print("✅ System initialized successfully!")
    
    yield
    
    # Cleanup
    print("🛑 Shutting down surveillance system...")
    camera_manager.stop_recording("spy")
    camera_manager.stop_all_cameras()
    print("✅ System shutdown complete!")


# Create FastAPI app
app = FastAPI(
    title="FastAPI Surveillance System",
    description="Advanced surveillance system with YOLO detection and sabotage capabilities",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/audio", StaticFiles(directory="audio"), name="audio")

# Add cache control middleware for audio files
@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    
    # Add no-cache headers for audio files and HTML pages to prevent caching issues
    if request.url.path.startswith("/audio/") or request.url.path in ["/", "/admin", "/mama"]:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    
    return response

# Setup templates
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(cameras.router)
app.include_router(sabotage.router)
app.include_router(streaming.router)
app.include_router(websockets.router)
app.include_router(mama.router)


# Callback functions for camera events
async def handle_person_detection(camera_id: str, frame, play_sound: bool = True):
    """Handle person detection event"""
    try:
        # Send WebSocket notification
        await connection_manager.send_person_detection_alert(
            camera_id=camera_id,
            frame=frame,
            play_sound=play_sound
        )
        
        # Play audio notification
        if play_sound and audio_manager.is_available():
            audio_manager.play_detection_alert()
        
        print(f"Person detected in camera {camera_id}")
    
    except Exception as e:
        print(f"Error handling person detection: {e}")


async def handle_camera_status(event_type: str, data: dict):
    """Handle camera status events"""
    try:
        if event_type == "mama_camera_toggle":
            # Send high priority alert for mama camera toggle
            await connection_manager.send_high_priority_alert(
                alert_type="mama_camera_access",
                message_text=f"Mama camera access {'enabled' if data.get('enabled') else 'disabled'}",
                data=data
            )
            # Broadcast explicit mama status for real-time UI updates
            enabled = bool(data.get("enabled"))
            await connection_manager.send_mama_status_update(enabled)
        
        print(f"Camera status event: {event_type} - {data}")
    
    except Exception as e:
        print(f"Error handling camera status: {e}")


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Handle 404 errors"""
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error_code": 404,
            "error_message": "Page not found"
        },
        status_code=404
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: HTTPException):
    """Handle 500 errors"""
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error_code": 500,
            "error_message": "Internal server error"
        },
        status_code=500
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "services": {
            "cameras": len(camera_manager.cameras),
            "active_cameras": sum(1 for active in camera_manager.camera_active.values() if active),
            "websocket_connections": len(connection_manager.admin_connections) + len(connection_manager.mama_connections),
            "audio_available": audio_manager.is_available()
        }
    }


# Status endpoint for frontend
@app.get("/get_status")
async def get_status():
    """Get system status for frontend"""
    try:
        # Get camera list
        cameras = camera_manager.get_camera_list()
        
        # Get sabotage status
        sabotage_status = {
            "current_mode": "normal",  # Default mode
            "is_auto_running": False,
            "is_preemptive_active": False,
            "fps": None,
            "target_camera": None
        }
        
        # Get mama status
        mama_connections = len(connection_manager.mama_connections)
        mama_status = {
            "status": "online" if mama_connections > 0 else "offline",
            "connections": mama_connections
        }
        
        return {
            "cameras": cameras,
            "sabotage_status": sabotage_status,
            "mama_status": mama_status,
            "connected_users": len(connection_manager.admin_connections) + len(connection_manager.mama_connections),
            "mama_login_count": mama_connections
        }
        
    except Exception as e:
        print(f"Error getting status: {e}")
        return {
            "cameras": [],
            "sabotage_status": {"current_mode": "normal"},
            "mama_status": {"status": "offline"},
            "connected_users": 0,
            "mama_login_count": 0
        }


# API info endpoint
@app.get("/api/info")
async def api_info():
    """API information endpoint"""
    return {
        "name": "FastAPI Surveillance System",
        "version": "2.0.0",
        "description": "Advanced surveillance system with YOLO detection and sabotage capabilities",
        "endpoints": {
            "authentication": "/api/login, /api/logout",
            "cameras": "/api/cameras",
            "sabotage": "/api/sabotage",
            "streaming": "/api/stream",
            "websocket": "/ws"
        },
        "features": [
            "YOLO person detection",
            "Real-time video streaming",
            "Sabotage modes",
            "WebSocket communication",
            "Session-based authentication",
            "Admin panel",
            "IP camera support"
        ]
    }


if __name__ == "__main__":
    print("🎯 Starting FastAPI Surveillance System...")
    print(f"📊 Configuration:")
    print(f"   - Host: {settings.host}")
    print(f"   - Port: {settings.port}")
    print(f"   - Debug: {settings.debug}")
    print(f"   - YOLO Model: {settings.yolo_model_path}")
    print("""
██████╗  █████╗ ██████╗ ██╗ ██████╗     ███████╗███████╗██████╗ ██╗   ██╗██╗ ██████╗███████╗
██╔══██╗██╔══██╗██╔══██╗██║██╔═══██╗    ██╔════╝██╔════╝██╔══██╗██║   ██║██║██╔════╝██╔════╝
██║  ██║███████║██████╔╝██║██║   ██║    ███████╗█████╗  ██████╔╝██║   ██║██║██║     █████╗  
██║  ██║██╔══██║██╔══██╗██║██║   ██║    ╚════██║██╔══╝  ██╔══██╗╚██╗ ██╔╝██║██║     ██╔══╝  
██████╔╝██║  ██║██║  ██║██║╚██████╔╝    ███████║███████╗██║  ██║ ╚████╔╝ ██║╚██████╗███████╗
╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝ ╚═════╝     ╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚═╝ ╚═════╝╚══════╝
                                                                                            """)
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )
