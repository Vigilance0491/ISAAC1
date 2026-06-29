import datetime as dt
import http.client
import threading
from http.server import ThreadingHTTPServer

from isaac1.control_server import (
    AuthManager,
    AuthUser,
    ControlState,
    INDEX_HTML,
    LowBatteryMode,
    MACKAY_TIMEZONE,
    MIN_AVERAGE_INTERVAL_MINUTES,
    hash_password,
    make_handler,
    verify_password,
)


class FakeHardwareClient:
    def __init__(self):
        self.calls = []

    def set_relay(self, relay, enabled):
        self.calls.append(("relay", relay, enabled))
        return {"ok": True}

    def set_volume(self, volume):
        self.calls.append(("volume", volume))
        return {"ok": True}

    def start_sound(self, file_id):
        self.calls.append(("start", file_id))
        return {"ok": True}


class FakeRut241InputProvider:
    def __init__(self, states):
        self.states = list(states)
        self.calls = 0

    def get_input_state(self):
        self.calls += 1
        state = self.states.pop(0)
        if isinstance(state, Exception):
            raise state
        return state


def daylight_now():
    return dt.datetime(2026, 6, 27, 12, 0, tzinfo=MACKAY_TIMEZONE)


def night_now():
    return dt.datetime(2026, 6, 27, 22, 0, tzinfo=MACKAY_TIMEZONE)


def test_gas_gun_button_controls_relay_two():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now)

    state.toggle_unit()
    assert state.toggle_gas_gun()["gasGun"] is True
    assert state.toggle_gas_gun()["gasGun"] is False

    assert client.calls == [
        ("relay", 2, True),
        ("relay", 2, False),
    ]


def test_sound_button_controls_amplifier_and_mutes_without_restarting():
    client = FakeHardwareClient()
    state = ControlState(client, sound_file_id=20, now_provider=daylight_now)

    state.toggle_unit()
    assert state.toggle_sound()["sound"] is True
    assert state.toggle_sound()["sound"] is False
    assert state.toggle_sound()["sound"] is True

    assert client.calls == [
        ("relay", 1, True),
        ("volume", 100),
        ("start", 20),
        ("volume", 0),
        ("relay", 1, False),
        ("relay", 1, True),
        ("volume", 100),
    ]


def test_gas_gun_off_prevents_timer_gas_pulse():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now)

    state.toggle_unit()
    state.toggle_random_timer()
    assert state.toggle_gas_gun_off()["gasGunOff"] is True
    assert state._set_timer_gas_gun(True) is True

    assert ("relay", 2, True) not in client.calls


def test_timer_average_interval_has_lower_bound():
    client = FakeHardwareClient()
    state = ControlState(client)

    for _ in range(20):
        state.adjust_average_interval(-1)

    assert state.snapshot()["averageIntervalMinutes"] == MIN_AVERAGE_INTERVAL_MINUTES


def test_unit_cannot_turn_on_outside_mackay_daylight():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=night_now)

    try:
        state.toggle_unit()
    except RuntimeError as exc:
        assert "outside Mackay daylight hours" in str(exc)
    else:
        raise AssertionError("expected daylight guard")

    assert state.snapshot()["unitOn"] is False


def test_control_page_has_iphone_home_screen_metadata():
    assert 'apple-mobile-web-app-capable' in INDEX_HTML
    assert 'rel="manifest"' in INDEX_HTML
    assert 'rel="apple-touch-icon"' in INDEX_HTML


def test_control_page_has_low_battery_button_styles():
    assert '#unitOn[data-low-battery="false"][data-active="false"]' in INDEX_HTML
    assert '#unitOn[data-low-battery="false"][data-active="true"]' in INDEX_HTML
    assert '#unitOn[data-low-battery="true"]' in INDEX_HTML
    assert INDEX_HTML.count("@keyframes lowBatteryFlash") == 1


def test_rut_input_high_at_startup_keeps_unit_button_normal():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now, start_background_threads=False)

    snapshot = state.apply_rut241_input_state("HIGH")

    assert snapshot["lowBatteryOverride"] is False
    assert snapshot["unitButtonEnabled"] is True
    assert snapshot["unitButtonVisualState"] == "off"
    assert state.toggle_unit()["unitOn"] is True


def test_rut_input_low_at_startup_disables_unit_button():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now, start_background_threads=False)

    snapshot = state.apply_rut241_input_state("LOW")

    assert snapshot["lowBatteryOverride"] is True
    assert snapshot["lowBatteryMode"] == LowBatteryMode.LOW_BATTERY_OVERRIDE.value
    assert snapshot["unitButtonEnabled"] is False
    assert snapshot["unitButtonLabel"] == "LOW BATTERY"
    assert snapshot["unitButtonVisualState"] == "low-battery"
    try:
        state.toggle_unit()
    except RuntimeError as exc:
        assert "low battery" in str(exc)
    else:
        raise AssertionError("expected low-battery guard")


def test_rut_input_high_to_low_saves_state_once_and_blocks_operation():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now, start_background_threads=False)
    state.toggle_unit()

    snapshot = state.apply_rut241_input_state("LOW")
    saved_state = state._saved_unit_button_state
    repeated_snapshot = state.apply_rut241_input_state("LOW")

    assert snapshot["unitOn"] is False
    assert saved_state is not None
    assert saved_state.unit_on is True
    assert state._saved_unit_button_state is saved_state
    assert repeated_snapshot["lowBatteryOverride"] is True
    try:
        state.toggle_unit()
    except RuntimeError as exc:
        assert "low battery" in str(exc)
    else:
        raise AssertionError("expected low-battery guard")


def test_rut_input_low_to_high_restores_saved_unit_state():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now, start_background_threads=False)
    state.toggle_unit()
    state.apply_rut241_input_state("LOW")

    snapshot = state.apply_rut241_input_state("HIGH")

    assert snapshot["unitOn"] is True
    assert snapshot["lowBatteryOverride"] is False
    assert snapshot["unitButtonEnabled"] is True
    assert snapshot["unitButtonVisualState"] == "on"
    assert state._saved_unit_button_state is None


def test_rut_input_low_to_unknown_keeps_safe_override():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now, start_background_threads=False)
    state.toggle_unit()
    state.apply_rut241_input_state("LOW")

    snapshot = state.apply_rut241_input_state("UNKNOWN")

    assert snapshot["unitOn"] is False
    assert snapshot["lowBatteryOverride"] is True
    assert snapshot["lowBatteryMode"] == LowBatteryMode.UNKNOWN_WHILE_LOW.value
    assert snapshot["unitButtonVisualState"] == "low-battery"


def test_rut_input_unknown_to_high_only_restores_after_low_latch():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now, start_background_threads=False)

    snapshot = state.apply_rut241_input_state("UNKNOWN")
    assert snapshot["lowBatteryOverride"] is False

    snapshot = state.apply_rut241_input_state("HIGH")
    assert snapshot["unitOn"] is False
    assert snapshot["lowBatteryOverride"] is False

    state.toggle_unit()
    state.apply_rut241_input_state("LOW")
    state.apply_rut241_input_state("UNKNOWN")
    snapshot = state.apply_rut241_input_state("HIGH")

    assert snapshot["unitOn"] is True
    assert snapshot["lowBatteryOverride"] is False


def test_rut_input_multiple_low_high_cycles_save_and_restore_each_cycle():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now, start_background_threads=False)

    state.apply_rut241_input_state("LOW")
    snapshot = state.apply_rut241_input_state("HIGH")
    assert snapshot["unitOn"] is False

    state.toggle_unit()
    state.apply_rut241_input_state("LOW")
    snapshot = state.apply_rut241_input_state("HIGH")
    assert snapshot["unitOn"] is True


def test_rut_input_provider_mock_drives_polling_and_unknown_failure_latches_low():
    client = FakeHardwareClient()
    provider = FakeRut241InputProvider(["LOW", RuntimeError("connection failed"), "HIGH"])
    state = ControlState(
        client,
        now_provider=daylight_now,
        input_provider=provider,
        start_background_threads=False,
    )

    assert state.poll_rut241_input_once()["lowBatteryOverride"] is True
    unknown = state.poll_rut241_input_once()
    assert unknown["lowBatteryOverride"] is True
    assert unknown["lowBatteryMode"] == LowBatteryMode.UNKNOWN_WHILE_LOW.value
    assert state.poll_rut241_input_once()["lowBatteryOverride"] is False
    assert provider.calls == 3


def test_password_hash_verification():
    stored_hash = hash_password("correct horse battery staple", salt="fixed-salt")

    assert verify_password("correct horse battery staple", stored_hash)
    assert not verify_password("wrong password", stored_hash)


def test_api_requires_login_when_auth_enabled():
    client = FakeHardwareClient()
    state = ControlState(client, now_provider=daylight_now)
    auth = AuthManager(
        [AuthUser("operator", "operator", hash_password("secret", salt="test-salt"))]
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state, auth))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        connection = http.client.HTTPConnection(*server.server_address)
        connection.request("POST", "/api/unit/toggle", body="")
        response = connection.getresponse()
        response.read()
        assert response.status == 401
        connection.close()

        body = "username=operator&password=secret"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
        }
        connection = http.client.HTTPConnection(*server.server_address)
        connection.request("POST", "/login", body=body, headers=headers)
        response = connection.getresponse()
        response.read()
        cookie = response.getheader("Set-Cookie")
        assert response.status == 303
        assert cookie
        connection.close()

        connection = http.client.HTTPConnection(*server.server_address)
        connection.request("POST", "/api/unit/toggle", body="", headers={"Cookie": cookie})
        response = connection.getresponse()
        response.read()
        assert response.status == 200
        connection.close()
    finally:
        server.shutdown()
