"""Ajustes de la tele: archivo, validación y endpoints solo de admin."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.config import TvOverlayConfig
from routers.tv import router
from services.tv_notifier import TvOverlayNotifier
from services.tv_settings import TvSettingsError, TvSettingsStore
from utils.auth import SessionManager, create_user_jwt


def valid(**overrides):
    data = {
        "enabled": True,
        "tv_ip": "192.168.1.80",
        "adb_port": 5555,
        "adb_path": "adb",
        "title": "Alerta",
        "duration": 8,
        "cooldown_seconds": 30,
        "rest_fallback": True,
        "tvoverlay_port": 5001,
        "adb_local_port": 15001,
    }
    data.update(overrides)
    return data


class Result:
    def __init__(self, code=0, out="", err=""):
        self.returncode = code
        self.stdout = out
        self.stderr = err


@pytest.fixture
def store(tmp_path):
    return TvSettingsStore(tmp_path / "tv_settings.json")


def test_defaults_come_from_config_until_saved(store):
    snap = store.snapshot()
    assert snap["enabled"] is bool(TvOverlayConfig.enabled)
    assert snap["adb_port"] == int(TvOverlayConfig.adb_port)
    assert snap["tvoverlay_port"] == int(TvOverlayConfig.tvoverlay_port)
    assert snap["rest_fallback"] is True
    assert not store.path.exists()


def test_save_persists_and_beats_config_defaults(store, monkeypatch):
    saved = store.update(valid(tv_ip="192.168.1.20", adb_port="5556", cooldown_seconds="12.5", title="Ojo"))
    assert saved["tv_ip"] == "192.168.1.20"
    assert saved["adb_port"] == 5556
    assert saved["cooldown_seconds"] == 12.5
    assert store.path.is_file()

    monkeypatch.setattr(TvOverlayConfig, "tv_ip", "10.1.1.1", raising=False)
    monkeypatch.setattr(TvOverlayConfig, "enabled", False, raising=False)
    assert store.snapshot()["tv_ip"] == "192.168.1.20"
    assert store.snapshot()["enabled"] is True

    reloaded = TvSettingsStore(store.path)
    assert reloaded.snapshot()["title"] == "Ojo"
    assert reloaded.snapshot()["cooldown_seconds"] == 12.5
    assert reloaded.snapshot()["adb_port"] == 5556


def test_invalid_values_are_spanish_and_do_not_write(store):
    with pytest.raises(TvSettingsError) as caught:
        store.update(valid(
            tv_ip="999.1.1.1",
            adb_port=0,
            duration=-3,
            cooldown_seconds=0,
            adb_path="",
            title="x" * 81,
        ))
    message = caught.value.message
    assert "IP" in message
    assert "65535" in message
    assert "duración" in message
    assert "cooldown" in message
    assert "adb" in message
    assert "título" in message
    assert not store.path.exists()
    assert store.snapshot()["tv_ip"] == str(TvOverlayConfig.tv_ip or "").strip()


def test_enabled_requires_ip_but_off_can_be_empty(store):
    with pytest.raises(TvSettingsError) as caught:
        store.update(valid(enabled=True, tv_ip=""))
    assert "Pon la IP" in caught.value.message
    saved = store.update(valid(enabled=False, tv_ip="", rest_fallback=False))
    assert saved["enabled"] is False
    assert saved["tv_ip"] == ""
    assert saved["rest_fallback"] is False


def test_bool_is_not_a_port(store):
    with pytest.raises(TvSettingsError) as caught:
        store.update(valid(adb_port=True, tvoverlay_port=False))
    assert "puerto ADB" in caught.value.message
    assert "API de TvOverlay" in caught.value.message


def test_check_does_not_persist(store):
    checked = store.check(valid(tv_ip="10.2.2.2", duration="9"))
    assert checked["tv_ip"] == "10.2.2.2"
    assert checked["duration"] == 9
    assert store.snapshot()["tv_ip"] != "10.2.2.2"
    assert not store.path.exists()


def test_saved_settings_apply_live_to_the_notifier(store, monkeypatch):
    store.update(valid(
        tv_ip="10.4.4.4",
        adb_port=5557,
        adb_path="adb-custom",
        adb_local_port=16001,
        tvoverlay_port=5001,
    ))
    monkeypatch.setattr("services.tv_notifier.tv_settings", store)
    calls = []

    def runner(args, timeout):
        calls.append(list(args))
        if args[1] == "devices":
            return Result(0, "List of devices attached\n10.4.4.4:5557\tdevice\n", "")
        return Result(0, "", "")

    posts = []

    def http_post(url, payload, timeout):
        posts.append((url, payload))
        return True

    notifier = TvOverlayNotifier(runner=runner, http_post=http_post)
    assert notifier.send_notification("Cámara 1 detectó a una persona") is True
    assert calls[0][0] == "adb-custom"
    assert ["adb-custom", "-s", "10.4.4.4:5557", "forward", "tcp:16001", "tcp:5001"] in calls
    assert posts[0][0] == "http://127.0.0.1:16001/notify"

    unsaved = store.check(valid(tv_ip="10.8.8.8", adb_port=5557, adb_path="adb-custom"))
    calls.clear()
    posts.clear()
    assert notifier.send_notification("prueba", settings=unsaved) is True
    assert any("10.8.8.8:5557" in part for call in calls for part in call)
    assert store.snapshot()["tv_ip"] == "10.4.4.4"


def test_rest_fallback_can_be_turned_off(store, monkeypatch):
    store.update(valid(rest_fallback=False, tv_ip="10.5.5.5"))
    monkeypatch.setattr("services.tv_notifier.tv_settings", store)
    posts = []

    def runner(args, timeout):
        if len(args) >= 2 and args[1] == "devices":
            return Result(0, "List of devices attached\n", "")
        return Result(1, "", "no")

    def http_post(url, payload, timeout):
        posts.append(url)
        return True

    notifier = TvOverlayNotifier(runner=runner, http_post=http_post)
    result = notifier.send_detailed("Cámara 1 detectó a una persona")
    assert result["ok"] is False
    assert result["via"] is None
    assert "respaldo" in result["detail"]
    assert posts == []


def test_form_lives_only_in_the_admin_panel():
    text = Path("templates/index.html").read_text(encoding="utf-8")
    start = text.index("{% if rol == 'admin' %}")
    end = text.index("{% endif %}", start)
    block = text[start:end]
    assert 'id="tv-settings-form"' in block
    assert 'id="btn-test-tv"' in block
    assert "tv-settings-form" not in text[end:]
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "data/tv_settings.json" in gitignore


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = TvSettingsStore(tmp_path / "tv_settings.json")
    monkeypatch.setattr("routers.tv.tv_settings", store)
    monkeypatch.setattr("services.tv_notifier.tv_settings", store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    admin_id = SessionManager.create_session("admin", "admin")
    mama_id = SessionManager.create_session("1234", "mama")
    mama_jwt = create_user_jwt("1234", "mama")
    return {
        "client": client,
        "store": store,
        "admin": {"session_id": admin_id},
        "mama": {"session_id": mama_id, "mama_jwt": mama_jwt},
    }


def test_settings_require_admin(api):
    client = api["client"]
    assert client.get("/api/tv/settings").status_code == 401
    assert client.put("/api/tv/settings", json=valid()).status_code == 401
    assert client.post("/api/tv/test", json=valid()).status_code == 401

    mama = api["mama"]
    assert client.get("/api/tv/settings", cookies=mama).status_code == 403
    assert client.put("/api/tv/settings", cookies=mama, json=valid()).status_code == 403
    assert client.post("/api/tv/test", cookies=mama, json=valid()).status_code == 403


def test_admin_can_save_and_read_back(api):
    client = api["client"]
    denied = client.put(
        "/api/tv/settings",
        cookies=api["admin"],
        json=valid(tv_ip="no-es-ip", adb_port=70000),
    )
    assert denied.status_code == 400
    body = denied.json()
    assert body["success"] is False
    assert "IP" in body["message"]
    assert "65535" in body["message"]
    assert "tv_ip" in body["data"]["errors"]
    assert not api["store"].path.exists()

    saved = client.put(
        "/api/tv/settings",
        cookies=api["admin"],
        json=valid(tv_ip="10.0.0.8", duration="6", cooldown_seconds="15"),
    )
    assert saved.status_code == 200
    assert saved.json()["message"].startswith("Ajustes guardados")
    assert saved.json()["data"]["tv_ip"] == "10.0.0.8"

    again = client.get("/api/tv/settings", cookies=api["admin"])
    assert again.status_code == 200
    assert again.json()["data"]["duration"] == 6
    assert again.json()["data"]["cooldown_seconds"] == 15
    on_disk = json.loads(api["store"].path.read_text(encoding="utf-8"))
    assert on_disk["tv_ip"] == "10.0.0.8"


def test_probe_uses_unsaved_form_and_reports_adb(api, monkeypatch):
    seen = {}

    def fake_detailed(message, title=None, duration=None, settings=None):
        seen["message"] = message
        seen["settings"] = settings
        return {"ok": True, "via": "adb", "detail": "Conectado por ADB. Aviso enviado a la tele."}

    monkeypatch.setattr("routers.tv.tv_notifier.send_detailed", fake_detailed)
    response = api["client"].post(
        "/api/tv/test",
        cookies=api["admin"],
        json=valid(tv_ip="10.9.9.9", title="Prueba"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["via"] == "adb"
    assert "ADB" in payload["message"]
    assert seen["message"] == "Cámara 1 detectó a una persona"
    assert seen["settings"]["tv_ip"] == "10.9.9.9"
    assert seen["settings"]["title"] == "Prueba"
    assert api["store"].snapshot()["tv_ip"] != "10.9.9.9"

    bad = api["client"].post("/api/tv/test", cookies=api["admin"], json=valid(cooldown_seconds=-1))
    assert bad.status_code == 400
    assert "cooldown" in bad.json()["message"]
    assert seen["settings"]["tv_ip"] == "10.9.9.9"
