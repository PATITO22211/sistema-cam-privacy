"""Aviso a la Android TV con TvOverlay, sin frenar la detección.

TvOverlay no registra un broadcast de notificaciones (el APK solo expone el
servidor HTTP). El transporte pedido es ADB: `adb connect` y un `adb forward`
hacia el `POST /notify` documentado. Si ADB no llega, se intenta el mismo
JSON directo a `http://<tv_ip>:<puerto>/notify`.
"""
import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from models.config import TvOverlayConfig


NOTIFY_PATH = "/notify"
SOURCE_NAME = "Vigilancia"


def build_detection_message(camera_id: str, name: Optional[str], number: Optional[int]) -> str:
    """Texto en español: 'Cámara 1 detectó a una persona' o el nombre de la cámara."""
    return f"{_camera_label(camera_id, name, number)} detectó a una persona"


def _camera_label(camera_id: str, name: Optional[str], number: Optional[int]) -> str:
    num = number if isinstance(number, int) and number > 0 else _fallback_number(camera_id)
    raw = (name or "").strip()
    if raw and not _is_generic_name(raw, num, camera_id):
        return raw
    return f"Cámara {num}"


def _fallback_number(camera_id: str) -> int:
    if camera_id and camera_id.startswith(("admin_", "custom_")):
        tail = camera_id.split("_", 1)[1]
        if tail.isdigit():
            return int(tail) + 1
    return 1


def _is_generic_name(raw: str, number: int, camera_id: str) -> bool:
    folded = raw.casefold()
    generic = {
        (camera_id or "").casefold(),
        f"admin camera {number}",
        f"cámara {number}",
        f"camara {number}",
        "spy camera",
        "admin camera",
    }
    return folded in generic


def _default_run(args, timeout):
    kwargs = {
        "args": args,
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "check": False,
    }
    if os.name == "nt":
        flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if flag:
            kwargs["creationflags"] = flag
    return subprocess.run(**kwargs)


def _default_http_post(url: str, payload: dict, timeout: float) -> bool:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = getattr(response, "status", None) or response.getcode()
            response.read(256)
            return 200 <= int(code) < 300
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(200).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        print(f"[TV] HTTP {exc.code} en {url}: {body}")
        return False


class TvOverlayNotifier:
    """Encola los avisos y los manda en un hilo aparte."""

    def __init__(self, runner: Optional[Callable] = None, http_post: Optional[Callable] = None):
        self._runner = runner or _default_run
        self._http_post = http_post or _default_http_post
        self._send_lock = threading.Lock()
        self._cooldown_lock = threading.Lock()
        self._last_sent = {}
        self._queue: queue.Queue = queue.Queue(maxsize=16)
        self._missing_ip_logged = False
        self._thread = threading.Thread(target=self._worker, name="tv-overlay", daemon=True)
        self._thread.start()

    def notify_detection(self, camera_id: str, name: Optional[str] = None, number: Optional[int] = None) -> None:
        """Regresa al instante. El hilo de video no espera a ADB."""
        try:
            if not TvOverlayConfig.enabled:
                return
            if not (TvOverlayConfig.tv_ip or "").strip():
                if not self._missing_ip_logged:
                    self._missing_ip_logged = True
                    self._log("avisos automáticos apagados: falta tv_ip en TvOverlayConfig")
                return
            now = time.monotonic()
            cooldown = float(TvOverlayConfig.cooldown_seconds)
            with self._cooldown_lock:
                last = self._last_sent.get(camera_id, 0.0)
                if now - last < cooldown:
                    return
                self._last_sent[camera_id] = now
            message = build_detection_message(camera_id, name, number)
            try:
                self._queue.put_nowait(message)
            except queue.Full:
                self._log("cola de avisos llena, se descarta uno")
        except Exception as exc:
            self._log(f"no se pudo encolar el aviso: {exc}")

    def send_notification(self, message: str, title: Optional[str] = None, duration: Optional[int] = None) -> bool:
        """Envío síncrono para la prueba. Nunca lanza: False si no se pudo."""
        try:
            with self._send_lock:
                return self._send_locked(message, title, duration)
        except Exception as exc:
            self._log(f"error enviando aviso: {exc}")
            return False

    def _send_locked(self, message: str, title: Optional[str], duration: Optional[int]) -> bool:
        ip = (TvOverlayConfig.tv_ip or "").strip()
        if not ip:
            self._log("falta tv_ip en TvOverlayConfig")
            return False

        serial = f"{ip}:{int(TvOverlayConfig.adb_port)}"
        payload = self._payload(message, title, duration)
        sent = False
        try:
            if self._ensure_connected(serial) and self._forward(serial):
                local_url = f"http://127.0.0.1:{int(TvOverlayConfig.adb_local_port)}{NOTIFY_PATH}"
                sent = self._post(local_url, payload)
                if sent:
                    self._log(f"aviso enviado por ADB: {message}")
                    return True
        except Exception as exc:
            self._log(f"ADB falló: {exc}")

        try:
            direct_url = f"http://{ip}:{int(TvOverlayConfig.tvoverlay_port)}{NOTIFY_PATH}"
            if self._post(direct_url, payload):
                self._log(f"aviso enviado por API directa: {message}")
                return True
        except Exception as exc:
            self._log(f"API directa falló: {exc}")

        self._log(f"no se pudo avisar a la tele: {message}")
        return False

    def _payload(self, message: str, title: Optional[str], duration: Optional[int]) -> dict:
        chosen_title = TvOverlayConfig.title if title is None else title
        chosen_duration = TvOverlayConfig.duration if duration is None else duration
        payload = {
            "message": message,
            "source": SOURCE_NAME,
            "duration": int(chosen_duration),
        }
        if chosen_title:
            payload["title"] = str(chosen_title)
        return payload

    def _ensure_connected(self, serial: str) -> bool:
        state = self._query_state(serial)
        if state == "device":
            return True
        self._log(f"ADB no está listo ({state or 'desconectado'}), reconectando {serial}")
        self._run([self._adb(), "connect", serial])
        state = self._query_state(serial)
        if state == "device":
            return True
        self._run([self._adb(), "disconnect", serial])
        self._run([self._adb(), "connect", serial])
        state = self._query_state(serial)
        if state != "device":
            self._log(f"adb connect no dejó la tele lista ({state or 'sin dispositivo'})")
        return state == "device"

    def _forward(self, serial: str) -> bool:
        local_port = int(TvOverlayConfig.adb_local_port)
        remote_port = int(TvOverlayConfig.tvoverlay_port)
        proc = self._run([
            self._adb(),
            "-s",
            serial,
            "forward",
            f"tcp:{local_port}",
            f"tcp:{remote_port}",
        ])
        if getattr(proc, "returncode", 1) != 0:
            detail = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()
            self._log(f"adb forward falló: {detail}")
            return False
        return True

    def _query_state(self, serial: str) -> Optional[str]:
        proc = self._run([self._adb(), "devices"])
        if getattr(proc, "returncode", 1) != 0:
            return None
        for line in (getattr(proc, "stdout", "") or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == serial:
                return parts[1]
        return None

    def _post(self, url: str, payload: dict) -> bool:
        return bool(self._http_post(url, payload, 5))

    def _run(self, args, timeout: float = 8):
        return self._runner(args, timeout)

    def _adb(self) -> str:
        path = (TvOverlayConfig.adb_path or "adb").strip()
        return path or "adb"

    def _worker(self) -> None:
        while True:
            message = self._queue.get()
            try:
                if message is None:
                    return
                self.send_notification(message)
            except Exception as exc:
                self._log(f"error en el hilo de avisos: {exc}")
            finally:
                self._queue.task_done()

    @staticmethod
    def _log(message: str) -> None:
        print(f"[TV] {message}")


tv_notifier = TvOverlayNotifier()
