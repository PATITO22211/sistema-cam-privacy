"""Aviso a la tele: ADB simulado, sin tocar una tele de verdad."""
import subprocess
import time

import pytest

from models.config import TvOverlayConfig, UserConfig
from services.tv_notifier import TvOverlayNotifier, build_detection_message


SERIAL = "192.168.1.50:5555"
ADB = "adb"


class Result:
    def __init__(self, code=0, out="", err=""):
        self.returncode = code
        self.stdout = out
        self.stderr = err


def _devices(state):
    if state is None:
        body = ""
    else:
        body = f"{SERIAL}\t{state}\n"
    return f"List of devices attached\n{body}"


class FakeAdb:
    def __init__(self, states):
        self.states = list(states)
        self.calls = []

    def __call__(self, args, timeout):
        self.calls.append(list(args))
        if len(args) >= 2 and args[1] == "devices":
            state = self.states.pop(0) if self.states else "device"
            return Result(0, _devices(state), "")
        if "forward" in args:
            return Result(0, "", "")
        return Result(0, "ok", "")


@pytest.fixture
def tv_config():
    fields = (
        "enabled",
        "tv_ip",
        "adb_port",
        "adb_path",
        "title",
        "duration",
        "cooldown_seconds",
        "tvoverlay_port",
        "adb_local_port",
    )
    saved = {name: getattr(TvOverlayConfig, name) for name in fields}
    TvOverlayConfig.enabled = True
    TvOverlayConfig.tv_ip = "192.168.1.50"
    TvOverlayConfig.adb_port = 5555
    TvOverlayConfig.adb_path = ADB
    TvOverlayConfig.title = "Alerta"
    TvOverlayConfig.duration = 8
    TvOverlayConfig.cooldown_seconds = 30
    TvOverlayConfig.tvoverlay_port = 5001
    TvOverlayConfig.adb_local_port = 15001
    yield
    for name, value in saved.items():
        setattr(TvOverlayConfig, name, value)


def _notifier(fake, posts, http_ok=True):
    def http_post(url, payload, timeout):
        posts.append((url, dict(payload)))
        if http_ok is True:
            return True
        if http_ok == "raise":
            raise OSError("red caída")
        return bool(http_ok)

    return TvOverlayNotifier(runner=fake, http_post=http_post)


def test_admin_password_is_admin():
    assert UserConfig.validate_credentials("admin", "admin")
    assert not UserConfig.validate_credentials("admin", "ad")
    assert UserConfig.validate_credentials("1234", "1234")


def test_readme_keeps_usage_and_comment():
    text = open("README.md", encoding="utf-8").read()
    assert "`admin` / `admin`" in text
    assert "`admin` / `ad`" not in text
    assert "<!-- Este proyecto nació" in text
    assert "TvOverlay" in text


def test_message_uses_number_or_custom_name():
    assert build_detection_message("admin_0", "Admin Camera 1", 1) == "Cámara 1 detectó a una persona"
    assert build_detection_message("admin_1", None, 2) == "Cámara 2 detectó a una persona"
    assert build_detection_message("spy", "Spy Camera", 3) == "Cámara 3 detectó a una persona"
    assert build_detection_message("admin_0", "Pasillo", 1) == "Pasillo detectó a una persona"


def test_sends_documented_notify_through_adb_when_already_connected(tv_config):
    fake = FakeAdb(["device"])
    posts = []
    notifier = _notifier(fake, posts)
    ok = notifier.send_notification("Cámara 1 detectó a una persona")
    assert ok is True
    assert [ADB, "connect", SERIAL] not in fake.calls
    assert [ADB, "-s", SERIAL, "forward", "tcp:15001", "tcp:5001"] in fake.calls
    assert posts == [
        (
            "http://127.0.0.1:15001/notify",
            {
                "title": "Alerta",
                "message": "Cámara 1 detectó a una persona",
                "source": "Vigilancia",
                "duration": 8,
            },
        )
    ]


def test_reconnects_when_adb_drops(tv_config):
    fake = FakeAdb(["offline", "device"])
    posts = []
    notifier = _notifier(fake, posts)
    assert notifier.send_notification("Cámara 2 detectó a una persona") is True
    assert [ADB, "connect", SERIAL] in fake.calls
    assert posts[0][0] == "http://127.0.0.1:15001/notify"
    assert posts[0][1]["message"] == "Cámara 2 detectó a una persona"


def test_rest_fallback_when_adb_cannot_connect(tv_config):
    fake = FakeAdb(["offline", "offline", None])
    posts = []
    notifier = _notifier(fake, posts)
    assert notifier.send_notification("hola") is True
    assert not any("forward" in call for call in fake.calls)
    assert [ADB, "disconnect", SERIAL] in fake.calls
    assert posts == [
        (
            "http://192.168.1.50:5001/notify",
            {
                "title": "Alerta",
                "message": "hola",
                "source": "Vigilancia",
                "duration": 8,
            },
        )
    ]


def test_rest_fallback_when_tunneled_post_fails(tv_config):
    fake = FakeAdb(["device"])
    posts = []

    def http_post(url, payload, timeout):
        posts.append(url)
        return "127.0.0.1" not in url

    notifier = TvOverlayNotifier(runner=fake, http_post=http_post)
    assert notifier.send_notification("Cámara 1 detectó a una persona") is True
    assert posts == [
        "http://127.0.0.1:15001/notify",
        "http://192.168.1.50:5001/notify",
    ]


def test_errors_are_swallowed(tv_config):
    def runner(args, timeout):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    def http_post(url, payload, timeout):
        raise ConnectionError("no hay tele")

    notifier = TvOverlayNotifier(runner=runner, http_post=http_post)
    assert notifier.send_notification("Cámara 1 detectó a una persona") is False


def test_detection_is_non_blocking_and_cooldown_is_per_camera(tv_config):
    fake = FakeAdb(["device"])
    posts = []
    started = time.monotonic()

    def slow_run(args, timeout):
        time.sleep(0.25)
        return fake(args, timeout)

    notifier = _notifier(slow_run, posts)
    notifier.notify_detection("admin_0", name="Admin Camera 1", number=1)
    elapsed = time.monotonic() - started
    assert elapsed < 0.15
    notifier.notify_detection("admin_0", name="Admin Camera 1", number=1)
    notifier.notify_detection("admin_1", name="Pasillo", number=2)
    notifier._queue.join()
    messages = [item[1]["message"] for item in posts]
    assert messages == [
        "Cámara 1 detectó a una persona",
        "Pasillo detectó a una persona",
    ]


def test_disabled_or_missing_ip_does_not_call_adb(tv_config):
    fake = FakeAdb(["device"])
    posts = []
    notifier = _notifier(fake, posts)
    TvOverlayConfig.enabled = False
    notifier.notify_detection("admin_0", name=None, number=1)
    notifier._queue.join()
    TvOverlayConfig.enabled = True
    TvOverlayConfig.tv_ip = "  "
    notifier.notify_detection("admin_0", name=None, number=1)
    notifier._queue.join()
    assert fake.calls == []
    assert posts == []
    assert notifier.send_notification("Cámara 1 detectó a una persona") is False


def test_custom_adb_path_is_used(tv_config):
    TvOverlayConfig.adb_path = r"C:\platform-tools\adb.exe"
    fake = FakeAdb(["device"])
    posts = []
    notifier = _notifier(fake, posts)
    assert notifier.send_notification("Cámara 1 detectó a una persona") is True
    assert fake.calls[0][0] == r"C:\platform-tools\adb.exe"
