"""
WebSocket routes for FastAPI surveillance system - Simplified for local use
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.websocket_service import websocket_endpoint
from utils.auth import session_manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_connection(websocket: WebSocket):
    """Simplified WebSocket endpoint without authentication for local system"""
    try:
        await websocket_endpoint(websocket, "admin", "local_user")
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass


@router.websocket("/ws/{session_id}")
async def websocket_with_session(websocket: WebSocket, session_id: str):
    """WebSocket endpoint that accepts a session_id path param.

    For local usage, it allows connections regardless of role.
    If the session exists, it uses the stored role and username;
    otherwise defaults to admin/local_user.
    """
    try:
        session = session_manager.get_session(session_id)
        if session:
            user_role = session.get("role", "admin")
            user_id = session.get("username", session_id)
        else:
            # Fallback for local use when no session is found
            user_role = "admin"
            user_id = f"guest_{session_id}"

        await websocket_endpoint(websocket, user_role, user_id)
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass