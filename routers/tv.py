"""Ajustes y prueba del aviso a la Android TV. Solo admin."""
import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from services.tv_notifier import tv_notifier
from services.tv_settings import TvSettingsError, tv_settings
from utils.auth import require_admin


router = APIRouter(prefix="/api/tv", tags=["tv"])


def _validation_error(exc: TvSettingsError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "message": exc.message,
            "data": {"errors": exc.errors},
        },
    )


def _bad_json() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "message": "No se pudo leer el formulario.",
            "data": {"errors": {}},
        },
    )


@router.get("/settings")
async def get_tv_settings(current_user: dict = Depends(require_admin)):
    return {"success": True, "message": "ok", "data": tv_settings.snapshot()}


@router.put("/settings")
async def put_tv_settings(request: Request, current_user: dict = Depends(require_admin)):
    try:
        raw = await request.json()
    except Exception:
        return _bad_json()
    try:
        saved = tv_settings.update(raw)
    except TvSettingsError as exc:
        return _validation_error(exc)
    return {
        "success": True,
        "message": "Ajustes guardados. Ya aplican, sin reiniciar.",
        "data": saved,
    }


@router.post("/test")
async def test_tv_notification(request: Request, current_user: dict = Depends(require_admin)):
    """Prueba con lo que venga en el body, aunque todavía no esté guardado."""
    raw = None
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            raw = await request.json()
        except Exception:
            return _bad_json()
    try:
        if isinstance(raw, dict) and raw:
            cfg = tv_settings.check(raw)
        else:
            cfg = tv_settings.snapshot()
    except TvSettingsError as exc:
        return _validation_error(exc)
    if not str(cfg.get("tv_ip") or "").strip():
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Pon la IP de la tele para probar.",
                "data": {"errors": {"tv_ip": "Pon la IP de la tele para probar."}},
            },
        )
    try:
        result = await asyncio.to_thread(
            lambda: tv_notifier.send_detailed("Cámara 1 detectó a una persona", settings=cfg)
        )
    except Exception as exc:
        return {
            "success": False,
            "message": f"No se pudo enviar: {exc}",
            "data": {"via": None},
        }
    return {
        "success": bool(result.get("ok")),
        "message": result.get("detail") or "No se pudo enviar.",
        "data": {"via": result.get("via")},
    }
