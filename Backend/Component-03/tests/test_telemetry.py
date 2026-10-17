"""Item 4: telemetry never stalls an audit — short timeouts, a retry cooldown
after a failed connect, a warning on every failure, and a bool return."""
import time

from app.services import telemetry


def _reset():
    telemetry._client = None
    telemetry._blocked_until = 0.0
    telemetry._connect_attempts = 0


def test_timeouts_and_cooldown_are_short():
    assert telemetry.CONNECT_TIMEOUT == 0.3
    assert telemetry.SOCKET_TIMEOUT == 0.3
    assert telemetry.RETRY_COOLDOWN == 30.0


def test_failed_connect_blocks_retry(monkeypatch):
    _reset()
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise OSError("no redis")

    monkeypatch.setattr(telemetry, "_connect", boom)
    try:
        assert telemetry._get_client() is None
        assert telemetry._get_client() is None  # still cooling down, no retry
        assert calls["n"] == 1
        assert telemetry._blocked_until > time.monotonic()
        assert telemetry._publish({"x": 1}) is False
    finally:
        _reset()


def test_publish_returns_true_on_success(monkeypatch):
    _reset()

    class FakeClient:
        def ping(self):
            return True

        def publish(self, channel, message):
            return 1

    monkeypatch.setattr(telemetry, "_connect", lambda: FakeClient())
    try:
        assert telemetry._publish({"x": 1}) is True
    finally:
        _reset()


def test_publish_warns_and_returns_false_on_failure(monkeypatch, caplog):
    _reset()

    class BadClient:
        def ping(self):
            return True

        def publish(self, channel, message):
            raise RuntimeError("down")

    monkeypatch.setattr(telemetry, "_connect", lambda: BadClient())
    try:
        with caplog.at_level("WARNING"):
            assert telemetry._publish({"x": 1}) is False
        assert any("publish failed" in r.message.lower() for r in caplog.records)
    finally:
        _reset()
