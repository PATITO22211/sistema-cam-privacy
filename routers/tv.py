"""Prueba manual del aviso a la Android TV."""
import asyncio

from fastapi import APIRouter, Depends

from models.config import TvOverlayConfig
from models.schemas import ApiResponse
from services.tv_notifier import tv_notifier
from utils.auth import require_admin


router = APIRouter(prefix="/api/tv", tags=["tv"])


@router.post("/test", response_model=ApiResponse)
async def test_tv_notification(current_user: dict = Depends(require_admin)):
    """Manda un aviso de prueba. No pasa por el cooldown de las cámaras."""
    message = "Cámara 1 detectó a una persona"
    if not (TvOverlayConfig.tv_ip or "").strip():
        return ApiResponse(
            success=False,
            message="Falta la IP de la tele en TvOverlayConfig (models/config.py)",
        )
    try:
        ok = await asyncio.to_thread(tv_notifier.send_notification, message)
    except Exception as exc:
        return ApiResponse(success=False, message=f"No se pudo enviar: {exc}")
    if ok:
        return ApiResponse(success=True, message="Aviso de prueba enviado a la tele")
    return ApiResponse(
        success=False,
        message="No se pudo enviar. Revisa la consola (ADB o TvOverlay)",
    )
