#!/usr/bin/env python3
"""Manda un aviso de prueba a la tele. No prende las cámaras ni el servidor.

Uso (desde la carpeta del proyecto):
    python scripts/test_tv_notify.py
    python scripts/test_tv_notify.py Cámara 2 detectó a una persona
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from models.config import TvOverlayConfig
from services.tv_notifier import tv_notifier


def main() -> int:
    message = " ".join(sys.argv[1:]).strip() or "Cámara 1 detectó a una persona"
    ip = (TvOverlayConfig.tv_ip or "").strip()
    if not TvOverlayConfig.enabled:
        print("TvOverlayConfig.enabled está en False. Este script igual intenta el aviso.")
        print("Los avisos automáticos siguen apagados hasta que lo pongas en True.")
    if not ip:
        print("Falta tv_ip en models/config.py, clase TvOverlayConfig.")
        return 1
    print(f"Enviando a {ip}:{TvOverlayConfig.adb_port} -> {message}")
    ok = tv_notifier.send_notification(message)
    if ok:
        print("Listo. Revisa la tele.")
        return 0
    print("No se pudo enviar. Mira los mensajes [TV] de arriba.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
