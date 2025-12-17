from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from models.schemas import UserLogin, LoginResponse, ApiResponse
from models.config import UserConfig
from utils.auth import (
    session_manager,
    authenticate_user,
    get_current_user_from_session,
    require_auth,
    kick_user_sessions,
    create_user_jwt,
    revoke_user_tokens,
)
from services.websocket_service import connection_manager
from services.audio_service import audio_manager

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login")
async def login_page(request: Request):
    """Display login page"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    redirect_url: str = Form(default="/"),
):
    try:
        user = authenticate_user(username, password)
        if not user:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "Invalid username or password",
                    "username": username,
                },
            )

        session_id = session_manager.create_session(user["username"], user["role"])

        jwt_token = None
        if user["role"] == "mama":
            try:
                jwt_token = create_user_jwt(user["username"], user["role"])
            except Exception as e:
                print(f"Error creating JWT for mama: {e}")

        if user["role"] == "admin":
            response = RedirectResponse(url="/admin", status_code=302)
        else:
            response = RedirectResponse(url="/dashboard", status_code=302)

        try:
            if user["role"] == "mama":
                await connection_manager.notify_mama_login(user["username"], session_id)
                audio_manager.play_notification(force=True)
        except Exception as e:
            print(f"Error notificando login de mamá: {e}")

        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=False,
            samesite="lax",
        )
        if jwt_token:
            response.set_cookie(
                key="mama_jwt",
                value=jwt_token,
                httponly=True,
                secure=False,
                samesite="lax",
            )

        return response

    except Exception:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Login failed. Please try again.",
                "username": username,
            },
        )


@router.post("/api/login")
async def api_login(login_data: UserLogin):
    try:
        user = authenticate_user(login_data.username, login_data.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        session_id = session_manager.create_session(user["username"], user["role"])

        jwt_token = None
        if user["role"] == "mama":
            try:
                jwt_token = create_user_jwt(user["username"], user["role"])
            except Exception as e:
                print(f"Error creating JWT for mama (API): {e}")

        try:
            if user["role"] == "mama":
                await connection_manager.notify_mama_login(user["username"], session_id)
                audio_manager.play_notification(force=True)
        except Exception as e:
            print(f"Error notificando login de mamá: {e}")

        return {
            "success": True,
            "message": "Login successful",
            "session_id": session_id,
            "user_role": user["role"],
            "redirect_url": "/admin" if user["role"] == "admin" else "/dashboard",
            "jwt_token": jwt_token,
        }

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Login failed")


@router.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("session_id")
    
    if session_id:
        session = session_manager.get_session(session_id)
        try:
            if session and session.get("role") == "mama":
                username = session.get("username", "mama")
                await connection_manager.mark_mama_intentional_logout(session.get("username", "mama"))
                revoke_user_tokens(username)
        except Exception as e:
            print(f"Error marking intentional mama logout: {e}")
        session_manager.delete_session(session_id)
    
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_id")
    response.delete_cookie("mama_jwt")
    
    return response


@router.post("/api/logout")
async def api_logout(request: Request):
    session_id = request.cookies.get("session_id")
    
    if session_id:
        session = session_manager.get_session(session_id)
        try:
            if session and session.get("role") == "mama":
                username = session.get("username", "mama")
                await connection_manager.mark_mama_intentional_logout(session.get("username", "mama"))
                revoke_user_tokens(username)
        except Exception as e:
            print(f"Error marking intentional mama logout (API): {e}")
        session_manager.delete_session(session_id)
    
    return ApiResponse(
        success=True,
        message="Logout successful"
    )


@router.get("/api/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user_from_session)):
    """Get current user information"""
    return {
        "user_id": current_user["user_id"],
        "role": current_user["role"],
        "session_id": current_user.get("session_id")
    }


@router.get("/api/sessions")
async def get_active_sessions(current_user: dict = Depends(require_auth)):
    """Get active sessions (admin only)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    sessions = session_manager.get_all_sessions()
    return {
        "sessions": sessions,
        "total": len(sessions)
    }


@router.delete("/api/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user: dict = Depends(require_auth)
):
    """Delete a specific session (admin only)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    # Inspect session before deletion to notify if it's mama
    session = session_manager.get_session(session_id)
    success = session_manager.delete_session(session_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        if session and session.get("role") == "mama":
            await connection_manager.mark_mama_intentional_logout(session.get("username", "mama"))
    except Exception as e:
        print(f"Error broadcasting mama logout on admin expel: {e}")
    
    return ApiResponse(
        success=True,
        message="Session deleted successfully"
    )


@router.post("/api/sessions/cleanup")
async def cleanup_sessions(current_user: dict = Depends(require_auth)):
    """Clean up expired sessions (admin only)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    cleaned = session_manager.cleanup_expired_sessions()
    
    return ApiResponse(
        success=True,
        message=f"Cleaned up {cleaned} expired sessions"
    )


@router.post("/api/expel-mama")
async def expel_mama_session(current_user: dict = Depends(require_auth)):
    """Expel all mama sessions (admin only)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    # Force close mama WebSockets with error-like message and redirect
    try:
        await connection_manager.force_close_mama(
            reason="Error de red",
            redirect_url="/login"
        )
    except Exception as e:
        print(f"Error forcing mama WS close: {e}")

    # Delete all mama sessions and revoke JWT tokens
    try:
        expelled_count = kick_user_sessions(UserConfig.MAMA_USERNAME)
    except Exception as e:
        print(f"Error expelling mama sessions: {e}")
        expelled_count = 0
    try:
        revoke_user_tokens(UserConfig.MAMA_USERNAME)
    except Exception as e:
        print(f"Error revoking mama JWT tokens on expel: {e}")

    # Notify admins of intentional logout
    try:
        if expelled_count >= 0:
            await connection_manager.mark_mama_intentional_logout(UserConfig.MAMA_USERNAME)
    except Exception as e:
        print(f"Error broadcasting mama logout on expel: {e}")

    return ApiResponse(
        success=True,
        message=f"Expulsadas {expelled_count} sesiones de mamá y conexión cerrada"
    )
