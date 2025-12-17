"""
Sabotaje: rutas de control para efectos en la cámara espía
"""
import time
import asyncio
import random
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Dict, Any

from models.schemas import SabotageMode, ApiResponse
from models.config import UserConfig
from utils.auth import require_admin, kick_user_sessions, revoke_user_tokens
from utils.video_processing import sabotage_engine
from services.camera_service import camera_manager
from services.websocket_service import connection_manager

router = APIRouter(prefix="/api/sabotage", tags=["sabotage"])

# Tarea de modo auto
_auto_mode_task: Optional[asyncio.Task] = None

# Configuración por defecto de probabilidades y rangos de duración para AUTO
# Los pesos son relativos (no necesitan sumar 1). Duraciones en segundos.
# Para SLOW se permite configurar rango de FPS.
AUTO_MODE_CONFIG: Dict[SabotageMode, Dict[str, Any]] = {
    SabotageMode.NORMAL: {"weight": 0.05, "duration_min": 1, "duration_max": 2},
    SabotageMode.PIXEL: {"weight": 0.35, "duration_min": 3, "duration_max": 10},
    SabotageMode.GRAY: {"weight": 0.10, "duration_min": 1, "duration_max": 1},
    SabotageMode.FREEZE: {"weight": 0.30, "duration_min": 1, "duration_max": 1},
    SabotageMode.SLOW: {"weight": 0.25, "duration_min": 4, "duration_max": 10, "fps_min": 1, "fps_max": 1},
    SabotageMode.STATIC: {"weight": 0.10, "duration_min": 1, "duration_max": 2},
}

AUTO_META_PROB_EXPEL_MAMA = 0.10
AUTO_META_PROB_DISABLE_CAMERA = 0.25
AUTO_META_PROB_ENABLE_CAMERA = 0.20


async def _auto_apply_access_actions():
    roll = random.random()
    threshold_expel = AUTO_META_PROB_EXPEL_MAMA
    threshold_disable = threshold_expel + AUTO_META_PROB_DISABLE_CAMERA
    threshold_enable = threshold_disable + AUTO_META_PROB_ENABLE_CAMERA
    try:
        if roll < threshold_expel:
            try:
                await connection_manager.force_close_mama(
                    reason="Error de red",
                    redirect_url="/login",
                )
            except Exception as e:
                print(f"Error in auto mode force_close_mama: {e}")
            try:
                expelled_count = kick_user_sessions(UserConfig.MAMA_USERNAME)
            except Exception as e:
                print(f"Error in auto mode kick_user_sessions: {e}")
                expelled_count = 0
            try:
                revoke_user_tokens(UserConfig.MAMA_USERNAME)
            except Exception as e:
                print(f"Error in auto mode revoke_user_tokens: {e}")
            try:
                if expelled_count >= 0:
                    await connection_manager.mark_mama_intentional_logout(UserConfig.MAMA_USERNAME)
            except Exception as e:
                print(f"Error in auto mode mark_mama_intentional_logout: {e}")
        elif roll < threshold_disable:
            try:
                camera_manager.set_mama_camera_enabled(False)
            except Exception as e:
                print(f"Error in auto mode disabling mama camera: {e}")
        elif roll < threshold_enable:
            try:
                camera_manager.set_mama_camera_enabled(True)
            except Exception as e:
                print(f"Error in auto mode enabling mama camera: {e}")
    except Exception as e:
        print(f"Unexpected error in _auto_apply_access_actions: {e}")


@router.get("/status")
async def get_sabotage_status() -> Dict[str, Any]:
    """Estado actual del sabotaje (incluye enabled y modos disponibles)."""
    interval = sabotage_engine.fps_reduction_interval or 0.0
    fps = int(1.0 / interval) if interval > 0 else None
    return {
        "enabled": sabotage_engine.enabled,
        "current_mode": sabotage_engine.current_mode.value,
        "is_auto_running": bool(sabotage_engine.auto_mode_active),
        "is_preemptive_active": bool(sabotage_engine.preemptive_freeze_active),
        "fps": fps,
        "available_modes": [m.value for m in sabotage_engine.available_modes],
    }


@router.post("/mode")
async def set_sabotage_mode(body: Dict[str, Any], current_user: dict = Depends(require_admin)) -> ApiResponse:
    """Cambiar modo de sabotaje. Soporta 'slow' con parámetro 'fps'."""
    try:
        mode_str = (body.get("mode") or "").lower()
        if not mode_str:
            raise HTTPException(status_code=400, detail="Falta 'mode' en el cuerpo")

        # Mapear alias
        if mode_str == "lowfps":
            mode = SabotageMode.SLOW
            fps = int(body.get("fps") or 2)
            # Limitar FPS entre 1 y 5
            fps = max(1, min(5, fps))
        else:
            try:
                mode = SabotageMode(mode_str)
            except ValueError:
                raise HTTPException(status_code=400, detail="Modo de sabotaje inválido")
            fps = int(body.get("fps") or 2)
            # Limitar FPS entre 1 y 5 para modo SLOW
            fps = max(1, min(5, fps))

        # Habilitar automáticamente salvo modo normal
        sabotage_engine.set_enabled(mode != SabotageMode.NORMAL)
        if mode == SabotageMode.SLOW:
            sabotage_engine.set_mode(mode, fps=fps)
        else:
            sabotage_engine.set_mode(mode)

        await connection_manager.send_sabotage_status_update(
            mode=sabotage_engine.current_mode.value,
            enabled=sabotage_engine.enabled,
            details={"action": "mode_changed", "changed_by": current_user.get("user_id")}
        )

        return ApiResponse(
            success=True,
            message=f"Modo de sabotaje establecido a {sabotage_engine.current_mode.value}",
            data={"mode": sabotage_engine.current_mode.value, "enabled": sabotage_engine.enabled, "fps": fps if mode == SabotageMode.SLOW else None}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cambiando modo de sabotaje: {str(e)}")


@router.post("/enable")
async def enable_sabotage(current_user: dict = Depends(require_admin)) -> ApiResponse:
    """Habilitar sabotaje."""
    try:
        sabotage_engine.set_enabled(True)
        await connection_manager.send_sabotage_status_update(
            mode=sabotage_engine.current_mode.value,
            enabled=True,
            details={"action": "enabled", "changed_by": current_user.get("user_id")}
        )
        return ApiResponse(success=True, message="Sabotaje habilitado", data={"mode": sabotage_engine.current_mode.value})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error habilitando sabotaje: {str(e)}")


@router.post("/disable")
async def disable_sabotage(current_user: dict = Depends(require_admin)) -> ApiResponse:
    """Deshabilitar sabotaje."""
    try:
        sabotage_engine.set_enabled(False)
        await connection_manager.send_sabotage_status_update(
            mode=sabotage_engine.current_mode.value,
            enabled=False,
            details={"action": "disabled", "changed_by": current_user.get("user_id")}
        )
        return ApiResponse(success=True, message="Sabotaje deshabilitado")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deshabilitando sabotaje: {str(e)}")


async def _auto_mode_worker():
    """Ejecutor de modo auto: aplica efectos con pesos y rangos configurables."""
    sabotage_engine.auto_mode_active = True
    try:
        while sabotage_engine.auto_mode_active:
            # Construir lista de modos y pesos activos
            modes = []
            weights = []
            for m, cfg in AUTO_MODE_CONFIG.items():
                w = float(cfg.get("weight", 0))
                if w > 0:
                    modes.append(m)
                    weights.append(w)

            if not modes:
                # Si no hay modos configurados, caer a NORMAL por seguridad
                modes = [SabotageMode.NORMAL]
                weights = [1.0]

            # Elegir modo según pesos
            mode_choice = random.choices(modes, weights=weights, k=1)[0]
            cfg = AUTO_MODE_CONFIG.get(mode_choice, {})
            dmin = int(cfg.get("duration_min", 3))
            dmax = int(cfg.get("duration_max", 8))
            if dmax < dmin:
                dmax = dmin
            duration = random.uniform(dmin, dmax)

            # Gestionar parámetros especiales
            fps = None
            if mode_choice == SabotageMode.SLOW:
                fps_min = int(cfg.get("fps_min", 1))
                fps_max = int(cfg.get("fps_max", 5))
                if fps_max < fps_min:
                    fps_max = fps_min
                fps = random.randint(fps_min, fps_max)

            # Aplicar modo
            if mode_choice == SabotageMode.NORMAL:
                # Normal: deshabilitar sabotaje y establecer modo normal
                sabotage_engine.set_enabled(False)
                sabotage_engine.set_mode(SabotageMode.NORMAL)
            else:
                sabotage_engine.set_enabled(True)
                if mode_choice == SabotageMode.SLOW:
                    sabotage_engine.set_mode(SabotageMode.SLOW, fps=fps)
                else:
                    sabotage_engine.set_mode(mode_choice)

            await connection_manager.send_sabotage_status_update(
                mode=sabotage_engine.current_mode.value,
                enabled=sabotage_engine.enabled,
                details={"action": "auto_tick", "duration": duration, "fps": fps}
            )

            await _auto_apply_access_actions()

            await asyncio.sleep(duration)
    except asyncio.CancelledError:
        pass
    finally:
        sabotage_engine.auto_mode_active = False


@router.post("/auto/start")
async def start_auto_mode(current_user: dict = Depends(require_admin)) -> ApiResponse:
    """Inicia el modo auto (bucles de efectos aleatorios)."""
    try:
        global _auto_mode_task
        if _auto_mode_task and not _auto_mode_task.done():
            return ApiResponse(success=True, message="Modo auto ya está en ejecución")

        _auto_mode_task = asyncio.create_task(_auto_mode_worker(), name="sabotage_auto")
        return ApiResponse(success=True, message="Modo auto iniciado")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error iniciando modo auto: {str(e)}")


@router.post("/auto/stop")
async def stop_auto_mode(current_user: dict = Depends(require_admin)) -> ApiResponse:
    """Detiene el modo auto y vuelve a normal."""
    try:
        global _auto_mode_task
        sabotage_engine.auto_mode_active = False
        if _auto_mode_task:
            _auto_mode_task.cancel()
        sabotage_engine.set_mode(SabotageMode.NORMAL)
        sabotage_engine.set_enabled(False)
        await connection_manager.send_sabotage_status_update(
            mode=SabotageMode.NORMAL.value,
            enabled=False,
            details={"action": "auto_stopped", "changed_by": current_user.get("user_id")}
        )
        return ApiResponse(success=True, message="Modo auto detenido")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deteniendo modo auto: {str(e)}")


@router.post("/emergency-disable")
async def emergency_disable_sabotage(current_user: dict = Depends(require_admin)) -> ApiResponse:
    """Botón rojo: deshabilita todo el sabotaje inmediatamente."""
    try:
        sabotage_engine.set_enabled(False)
        sabotage_engine.set_mode(SabotageMode.NORMAL)
        await connection_manager.send_high_priority_alert(
            alert_type="emergency_disable",
            message_text="Sabotaje deshabilitado de emergencia",
            data={"disabled_by": current_user.get("user_id"), "timestamp": time.time()}
        )
        return ApiResponse(success=True, message="Emergencia: sabotaje deshabilitado")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en emergencia: {str(e)}")


@router.get("/modes")
async def get_available_modes() -> Dict[str, Any]:
    """Lista de modos disponibles con estado actual."""
    def _desc(mode: SabotageMode) -> str:
        mapping = {
            SabotageMode.NORMAL: "Video normal sin efectos",
            SabotageMode.PIXEL: "Pixelización para ocultar detalles",
            SabotageMode.GRAY: "Escala de grises",
            SabotageMode.FREEZE: "Congelar último frame",
            SabotageMode.SLOW: "Reducir FPS (lento)",
            SabotageMode.STATIC: "Overlay de 'cargando' (spinner)",
        }
        return mapping.get(mode, "Modo desconocido")

    return {
        "modes": [{"value": m.value, "name": m.value.title(), "description": _desc(m)} for m in sabotage_engine.available_modes],
        "current_mode": sabotage_engine.current_mode.value,
        "enabled": sabotage_engine.enabled,
    }


@router.get("/auto/config")
async def get_auto_config(current_user: dict = Depends(require_admin)) -> Dict[str, Any]:
    """Obtener configuración actual del modo AUTO (pesos y rangos)."""
    def serialize_cfg(mode: SabotageMode, cfg: Dict[str, Any]) -> Dict[str, Any]:
        out = {
            "mode": mode.value,
            "weight": float(cfg.get("weight", 0)),
            "duration_min": int(cfg.get("duration_min", 1)),
            "duration_max": int(cfg.get("duration_max", 1)),
        }
        if mode == SabotageMode.SLOW:
            out["fps_min"] = int(cfg.get("fps_min", 1))
            out["fps_max"] = int(cfg.get("fps_max", 5))
        return out

    return {
        "config": [serialize_cfg(m, cfg) for m, cfg in AUTO_MODE_CONFIG.items()]
    }


@router.post("/auto/config")
async def set_auto_config(body: Dict[str, Any], current_user: dict = Depends(require_admin)) -> ApiResponse:
    """Actualizar configuración del modo AUTO. Estructura esperada:
    {
      "config": [
        {"mode": "normal", "weight": 0.2, "duration_min": 1, "duration_max": 4},
        {"mode": "slow", "weight": 0.25, "duration_min": 4, "duration_max": 10, "fps_min": 1, "fps_max": 5},
        ...
      ]
    }
    """
    try:
        cfg_list = body.get("config")
        if not isinstance(cfg_list, list):
            raise HTTPException(status_code=400, detail="Se requiere 'config' como lista")

        updated = 0
        for item in cfg_list:
            mode_str = (item.get("mode") or "").lower()
            try:
                mode = SabotageMode(mode_str)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Modo inválido: {mode_str}")

            weight = float(item.get("weight", 0))
            dmin = int(item.get("duration_min", 1))
            dmax = int(item.get("duration_max", dmin))
            if dmin < 0 or dmax < 0:
                raise HTTPException(status_code=400, detail="Las duraciones deben ser >= 0")
            if dmax < dmin:
                dmax = dmin

            entry: Dict[str, Any] = {"weight": weight, "duration_min": dmin, "duration_max": dmax}
            if mode == SabotageMode.SLOW:
                fps_min = int(item.get("fps_min", 1))
                fps_max = int(item.get("fps_max", fps_min))
                if fps_min < 1:
                    fps_min = 1
                if fps_max < fps_min:
                    fps_max = fps_min
                entry["fps_min"] = fps_min
                entry["fps_max"] = fps_max

            AUTO_MODE_CONFIG[mode] = entry
            updated += 1

        return ApiResponse(success=True, message=f"Configuración AUTO actualizada ({updated} modos)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error actualizando configuración AUTO: {str(e)}")
