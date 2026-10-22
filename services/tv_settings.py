"""Ajustes de TvOverlay que el panel puede cambiar sin reiniciar.

Si todavía no hay archivo guardado, manda lo de `TvOverlayConfig`.
Cuando el admin guarda, eso queda en `data/tv_settings.json` y gana
sobre config.py hasta que lo vuelvan a editar.
"""
import ipaddress
import json
import os
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from models.config import TvOverlayConfig


SETTING_KEYS = (
    "enabled",
    "tv_ip",
    "adb_port",
    "adb_path",
    "title",
    "duration",
    "cooldown_seconds",
    "rest_fallback",
    "tvoverlay_port",
    "adb_local_port",
)


class TvSettingsError(Exception):
    def __init__(self, errors: Dict[str, str]):
        self.errors = dict(errors)
        self.message = " ".join(self.errors.values()) or "Revisa los datos."
        super().__init__(self.message)


def default_settings_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "data" / "tv_settings.json"


def config_defaults() -> dict:
    return {
        "enabled": bool(TvOverlayConfig.enabled),
        "tv_ip": str(TvOverlayConfig.tv_ip or "").strip(),
        "adb_port": int(TvOverlayConfig.adb_port),
        "adb_path": str(TvOverlayConfig.adb_path or "adb").strip() or "adb",
        "title": str(TvOverlayConfig.title or "").strip(),
        "duration": int(TvOverlayConfig.duration),
        "cooldown_seconds": float(TvOverlayConfig.cooldown_seconds),
        "rest_fallback": bool(getattr(TvOverlayConfig, "rest_fallback", True)),
        "tvoverlay_port": int(TvOverlayConfig.tvoverlay_port),
        "adb_local_port": int(TvOverlayConfig.adb_local_port),
    }


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in (0, 1):
        return bool(int(value))
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in ("true", "1", "si", "sí", "on", "yes"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    return None


def _as_int(value) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("-"):
            digits = text[1:]
            sign = -1
        else:
            digits = text
            sign = 1
        if digits.isdigit():
            return sign * int(digits)
    return None


def _as_float(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _parse_port(value) -> Optional[int]:
    number = _as_int(value)
    if number is None or number < 1 or number > 65535:
        return None
    return number


def normalize_and_validate(raw: dict) -> Tuple[dict, Dict[str, str]]:
    errors: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return {}, {"form": "Los ajustes tienen que ir en un objeto."}

    enabled = _as_bool(raw.get("enabled"))
    if enabled is None:
        errors["enabled"] = "El interruptor de avisos tiene que ser sí o no."

    ip_value = raw.get("tv_ip", "")
    ip_text = str(ip_value).strip() if ip_value is not None else ""
    ip_ok = ""
    if ip_text:
        try:
            ip_ok = str(ipaddress.IPv4Address(ip_text))
        except ValueError:
            errors["tv_ip"] = "La IP de la tele no es válida. Usa algo como 192.168.1.80."
    elif enabled is True:
        errors["tv_ip"] = "Pon la IP de la tele."

    adb_port = _parse_port(raw.get("adb_port"))
    if adb_port is None:
        errors["adb_port"] = "El puerto ADB tiene que ser un número entre 1 y 65535."

    overlay_port = _parse_port(raw.get("tvoverlay_port"))
    if overlay_port is None:
        errors["tvoverlay_port"] = "El puerto del API de TvOverlay tiene que estar entre 1 y 65535."

    local_port = _parse_port(raw.get("adb_local_port"))
    if local_port is None:
        errors["adb_local_port"] = "El puerto local del túnel ADB tiene que estar entre 1 y 65535."

    path_value = raw.get("adb_path", "")
    path_text = str(path_value).strip() if path_value is not None else ""
    if not path_text:
        errors["adb_path"] = "Pon la ruta de adb. Si ya está en el PATH, escribe adb."
    elif any(char in path_text for char in ("\n", "\r", "\x00")) or len(path_text) > 260:
        errors["adb_path"] = "La ruta de adb no es válida."

    title_value = raw.get("title", "")
    title_text = str(title_value).strip() if title_value is not None else ""
    if len(title_text) > 80:
        errors["title"] = "El título no puede pasar de 80 caracteres."

    duration = _as_int(raw.get("duration"))
    if duration is None or duration < 1 or duration > 3600:
        errors["duration"] = "La duración tiene que ser un número de segundos entre 1 y 3600."

    cooldown = _as_float(raw.get("cooldown_seconds"))
    if cooldown is None or cooldown <= 0 or cooldown > 86400:
        errors["cooldown_seconds"] = "El cooldown tiene que ser un número de segundos mayor que 0 y hasta 86400."

    rest_fallback = _as_bool(raw.get("rest_fallback"))
    if rest_fallback is None:
        errors["rest_fallback"] = "El respaldo por API tiene que ser sí o no."

    if errors:
        return {}, errors

    return {
        "enabled": enabled,
        "tv_ip": ip_ok,
        "adb_port": adb_port,
        "adb_path": path_text,
        "title": title_text,
        "duration": duration,
        "cooldown_seconds": cooldown,
        "rest_fallback": rest_fallback,
        "tvoverlay_port": overlay_port,
        "adb_local_port": local_port,
    }, {}


class TvSettingsStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else default_settings_path()
        self._lock = threading.RLock()
        self._saved: Optional[dict] = None
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.is_file():
                self._saved = None
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                normalized, errors = normalize_and_validate(raw)
                if errors or not isinstance(raw, dict):
                    print(f"[TV] ajustes guardados inválidos, se usan los de config.py: {errors}")
                    self._saved = None
                    return
                self._saved = normalized
            except Exception as exc:
                print(f"[TV] no se pudo leer {self.path}: {exc}")
                self._saved = None

    def snapshot(self) -> dict:
        with self._lock:
            data = config_defaults()
            if self._saved:
                data.update(self._saved)
            return data

    def update(self, raw: dict) -> dict:
        normalized = self.check(raw)
        with self._lock:
            self._write(normalized)
        return dict(normalized)

    def check(self, raw: dict) -> dict:
        """Valida sin guardar. Sirve para probar el formulario antes de darle a Guardar."""
        if not isinstance(raw, dict):
            raise TvSettingsError({"form": "Los ajustes tienen que ir en un objeto."})
        merged = self.snapshot()
        for key in SETTING_KEYS:
            if key in raw:
                merged[key] = raw[key]
        normalized, errors = normalize_and_validate(merged)
        if errors:
            raise TvSettingsError(errors)
        return normalized

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        self._saved = dict(data)


tv_settings = TvSettingsStore()
