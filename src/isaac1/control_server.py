"""Local web UI for controlling ISAAC1 field hardware over ZeroTier."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import html
import http.cookies
import json
import math
import os
import random
import secrets as token_secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence


DEFAULT_RUT241_URL = "http://10.23.48.89"
DEFAULT_FILE_ID = 20
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_AVERAGE_INTERVAL_MINUTES = 1
MIN_AVERAGE_INTERVAL_MINUTES = 1
MAX_AVERAGE_INTERVAL_MINUTES = 60
INTERVAL_STEP_MINUTES = 1
TIMER_SOUND_MIN_SECONDS = 15
TIMER_SOUND_MAX_SECONDS = 30
TIMER_GAS_GUN_SECONDS = 2
PASSWORD_HASH_ITERATIONS = 260_000
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60
MACKAY_LATITUDE = -21.1411
MACKAY_LONGITUDE = 149.1860
MACKAY_TIMEZONE = dt.timezone(dt.timedelta(hours=10), "AEST")
APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180">
<rect width="180" height="180" rx="32" fill="#14211b"/>
<circle cx="90" cy="90" r="58" fill="#14844a"/>
<path d="M55 98h70v18H55zm26-58h18v100H81z" fill="#fff"/>
</svg>
"""
WEB_MANIFEST = {
    "name": "ISAAC1 Control",
    "short_name": "ISAAC1",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#f6f7f4",
    "theme_color": "#14211b",
    "icons": [
        {
            "src": "/icon.svg",
            "sizes": "180x180",
            "type": "image/svg+xml",
            "purpose": "any maskable",
        }
    ],
}


class HardwareClient(Protocol):
    def set_relay(self, relay: int, enabled: bool) -> Mapping[str, Any]:
        ...

    def set_volume(self, volume: int) -> Mapping[str, Any]:
        ...

    def start_sound(self, file_id: int) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: str
    password_hash: str


@dataclass(frozen=True)
class AuthSession:
    username: str
    role: str
    expires_at: float


def hash_password(password: str, salt: Optional[str] = None) -> str:
    password_salt = salt or token_secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        password_salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${password_salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(digest.hex(), expected_hex)


class AuthManager:
    def __init__(
        self,
        users: Sequence[AuthUser] = (),
        cookie_secure: bool = False,
        cookie_name: str = "isaac1_session",
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> None:
        self.users = {user.username: user for user in users}
        self.cookie_secure = cookie_secure
        self.cookie_name = cookie_name
        self.session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, AuthSession] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.users)

    @classmethod
    def from_env(cls) -> "AuthManager":
        users_file = os.environ.get("ISAAC1_AUTH_USERS_FILE", "")
        if not users_file:
            return cls()

        with open(users_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        users = [
            AuthUser(
                username=str(item["username"]),
                role=str(item.get("role", "operator")),
                password_hash=str(item["password_hash"]),
            )
            for item in payload.get("users", [])
        ]
        if not users:
            raise RuntimeError(f"{users_file} does not define any users")

        return cls(
            users=users,
            cookie_secure=os.environ.get("ISAAC1_COOKIE_SECURE", "").lower()
            in {"1", "true", "yes"},
            cookie_name=os.environ.get("ISAAC1_SESSION_COOKIE", "isaac1_session"),
            session_ttl_seconds=int(
                os.environ.get("ISAAC1_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS)
            ),
        )

    def authenticate(self, username: str, password: str) -> Optional[AuthUser]:
        user = self.users.get(username)
        if user and verify_password(password, user.password_hash):
            return user
        return None

    def create_session_cookie(self, user: AuthUser) -> str:
        session_id = token_secrets.token_urlsafe(32)
        expires_at = time.time() + self.session_ttl_seconds
        with self._lock:
            self._sessions[session_id] = AuthSession(user.username, user.role, expires_at)
        return self._format_cookie(session_id, max_age=self.session_ttl_seconds)

    def clear_session_cookie(self, cookie_header: str) -> str:
        session_id = self._session_id_from_cookie(cookie_header)
        if session_id:
            with self._lock:
                self._sessions.pop(session_id, None)
        return self._format_cookie("", max_age=0)

    def current_user(self, cookie_header: str) -> Optional[AuthUser]:
        session_id = self._session_id_from_cookie(cookie_header)
        if not session_id:
            return None

        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if session.expires_at <= time.time():
                self._sessions.pop(session_id, None)
                return None
            return self.users.get(session.username)

    def _session_id_from_cookie(self, cookie_header: str) -> str:
        if not cookie_header:
            return ""
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(cookie_header)
        except http.cookies.CookieError:
            return ""
        morsel = cookie.get(self.cookie_name)
        return morsel.value if morsel else ""

    def _format_cookie(self, value: str, max_age: int) -> str:
        cookie = http.cookies.SimpleCookie()
        cookie[self.cookie_name] = value
        cookie[self.cookie_name]["path"] = "/"
        cookie[self.cookie_name]["httponly"] = True
        cookie[self.cookie_name]["samesite"] = "Lax"
        cookie[self.cookie_name]["max-age"] = str(max_age)
        if self.cookie_secure:
            cookie[self.cookie_name]["secure"] = True
        return cookie.output(header="").strip()


def _sun_time_utc(
    day: dt.date,
    latitude: float,
    longitude: float,
    zenith_degrees: float,
    sunrise: bool,
) -> dt.datetime:
    """Approximate sunrise/sunset time using NOAA's public algorithm."""
    day_of_year = day.timetuple().tm_yday
    lng_hour = longitude / 15.0
    base_hour = 6 if sunrise else 18
    approximate = day_of_year + ((base_hour - lng_hour) / 24.0)
    mean_anomaly = (0.9856 * approximate) - 3.289
    true_longitude = (
        mean_anomaly
        + (1.916 * math.sin(math.radians(mean_anomaly)))
        + (0.020 * math.sin(math.radians(2 * mean_anomaly)))
        + 282.634
    ) % 360.0
    right_ascension = math.degrees(
        math.atan(0.91764 * math.tan(math.radians(true_longitude)))
    ) % 360.0
    longitude_quadrant = math.floor(true_longitude / 90.0) * 90.0
    right_ascension_quadrant = math.floor(right_ascension / 90.0) * 90.0
    right_ascension = (right_ascension + longitude_quadrant - right_ascension_quadrant) / 15.0
    sin_declination = 0.39782 * math.sin(math.radians(true_longitude))
    cos_declination = math.cos(math.asin(sin_declination))
    cos_hour_angle = (
        math.cos(math.radians(zenith_degrees))
        - (sin_declination * math.sin(math.radians(latitude)))
    ) / (cos_declination * math.cos(math.radians(latitude)))
    if cos_hour_angle > 1 or cos_hour_angle < -1:
        raise ValueError("sunrise/sunset is not defined for this date and location")
    hour_angle = (
        360.0 - math.degrees(math.acos(cos_hour_angle))
        if sunrise
        else math.degrees(math.acos(cos_hour_angle))
    ) / 15.0
    local_mean_time = (
        hour_angle + right_ascension - (0.06571 * approximate) - 6.622
    )
    utc_hour = (local_mean_time - lng_hour) % 24.0
    hour = int(utc_hour)
    minute_float = (utc_hour - hour) * 60.0
    minute = int(minute_float)
    second = int(round((minute_float - minute) * 60.0))
    if second == 60:
        second = 0
        minute += 1
    if minute == 60:
        minute = 0
        hour = (hour + 1) % 24
    return dt.datetime.combine(day, dt.time(hour, minute, second, tzinfo=dt.timezone.utc))


def mackay_daylight_window(now: Optional[dt.datetime] = None) -> tuple[dt.datetime, dt.datetime]:
    current = now.astimezone(MACKAY_TIMEZONE) if now else dt.datetime.now(MACKAY_TIMEZONE)
    local_day = current.date()
    sunrise = _sun_time_utc(local_day, MACKAY_LATITUDE, MACKAY_LONGITUDE, 90.833, True)
    sunset = _sun_time_utc(local_day, MACKAY_LATITUDE, MACKAY_LONGITUDE, 90.833, False)
    sunrise_local = sunrise.astimezone(MACKAY_TIMEZONE)
    sunset_local = sunset.astimezone(MACKAY_TIMEZONE)
    if sunrise_local.date() > local_day:
        sunrise_local -= dt.timedelta(days=1)
    if sunrise_local.date() < local_day:
        sunrise_local += dt.timedelta(days=1)
    if sunset_local.date() > local_day:
        sunset_local -= dt.timedelta(days=1)
    if sunset_local.date() < local_day:
        sunset_local += dt.timedelta(days=1)
    return sunrise_local, sunset_local


def is_mackay_daylight(now: Optional[dt.datetime] = None) -> bool:
    current = now.astimezone(MACKAY_TIMEZONE) if now else dt.datetime.now(MACKAY_TIMEZONE)
    sunrise, sunset = mackay_daylight_window(current)
    return sunrise <= current <= sunset


@dataclass(frozen=True)
class HardwareResponse:
    ok: bool
    payload: Mapping[str, Any]


class TonmindOverRutClient:
    """Calls the RUT241 CGI wrappers that proxy to the Tonmind T21."""

    def __init__(self, base_url: str, token: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def set_relay(self, relay: int, enabled: bool) -> Mapping[str, Any]:
        action = "on" if enabled else "off"
        return self._get_json(
            "/cgi-bin/custom/isaac1-relay",
            {"relay": str(relay), "action": action},
        )

    def set_volume(self, volume: int) -> Mapping[str, Any]:
        return self._get_json(
            "/cgi-bin/custom/isaac1-audio",
            {"action": "volume", "volume": str(volume)},
        )

    def start_sound(self, file_id: int) -> Mapping[str, Any]:
        return self._get_json(
            "/cgi-bin/custom/isaac1-audio",
            {"action": "start", "fileid": str(file_id)},
        )

    def _get_json(self, path: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        query = dict(params)
        query["token"] = self.token
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"hardware returned HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"hardware is unreachable: {exc.reason}") from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"hardware returned invalid JSON: {body}") from exc

        if not payload.get("ok", False):
            raise RuntimeError(f"hardware command failed: {payload}")
        return payload


class ControlState:
    """In-memory button state and hardware command sequencing."""

    def __init__(
        self,
        client: HardwareClient,
        sound_file_id: int = DEFAULT_FILE_ID,
        now_provider: Optional[Callable[[], dt.datetime]] = None,
    ) -> None:
        self._client = client
        self._sound_file_id = sound_file_id
        self._now_provider = now_provider or (lambda: dt.datetime.now(MACKAY_TIMEZONE))
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._manual_sound = False
        self._manual_gas_gun = False
        self._timer_sound = False
        self._timer_gas_gun = False
        self.unit_on = False
        self.sound = False
        self.gas_gun = False
        self.random_timer = False
        self.gas_gun_off = False
        self.average_interval_minutes = DEFAULT_AVERAGE_INTERVAL_MINUTES
        self.last_error = ""
        self._sound_started = False
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()
        self._daylight_thread = threading.Thread(target=self._daylight_loop, daemon=True)
        self._daylight_thread.start()

    def _snapshot_unlocked(self) -> dict[str, Any]:
        daylight = self._daylight_status_unlocked()
        return {
            "unitOn": self.unit_on,
            "sound": self.sound,
            "gasGun": self.gas_gun,
            "randomTimer": self.random_timer,
            "gasGunOff": self.gas_gun_off,
            "averageIntervalMinutes": self.average_interval_minutes,
            "daylight": daylight["daylight"],
            "sunrise": daylight["sunrise"],
            "sunset": daylight["sunset"],
            "lastError": self.last_error,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._enforce_daylight_unlocked()
            return self._snapshot_unlocked()

    def toggle_unit(self) -> dict[str, Any]:
        with self._condition:
            if self.unit_on:
                self._force_unit_off_unlocked()
            else:
                self._require_daylight_unlocked()
                self.unit_on = True
                self.last_error = ""
            self._condition.notify_all()
            return self._snapshot_unlocked()

    def toggle_gas_gun(self) -> dict[str, Any]:
        with self._condition:
            next_state = not self._manual_gas_gun
            if next_state:
                self._require_operational_unlocked()
            self._manual_gas_gun = next_state
            self._sync_gas_gun_unlocked()
            return self._snapshot_unlocked()

    def toggle_sound(self) -> dict[str, Any]:
        with self._condition:
            next_state = not self._manual_sound
            if next_state:
                self._require_operational_unlocked()
            self._manual_sound = next_state
            self._sync_sound_unlocked()
            return self._snapshot_unlocked()

    def toggle_random_timer(self) -> dict[str, Any]:
        with self._condition:
            next_state = not self.random_timer
            if next_state:
                self._require_operational_unlocked()
                self.random_timer = True
            else:
                self.random_timer = False
                self._timer_sound = False
                self._timer_gas_gun = False
                self._sync_sound_unlocked()
                self._sync_gas_gun_unlocked()
            self.last_error = ""
            self._condition.notify_all()
            return self._snapshot_unlocked()

    def toggle_gas_gun_off(self) -> dict[str, Any]:
        with self._condition:
            self.gas_gun_off = not self.gas_gun_off
            if self.gas_gun_off:
                self._timer_gas_gun = False
                self._sync_gas_gun_unlocked()
            self._condition.notify_all()
            return self._snapshot_unlocked()

    def adjust_average_interval(self, delta_minutes: int) -> dict[str, Any]:
        with self._condition:
            self.average_interval_minutes = max(
                MIN_AVERAGE_INTERVAL_MINUTES,
                min(
                    MAX_AVERAGE_INTERVAL_MINUTES,
                    self.average_interval_minutes + delta_minutes,
                ),
            )
            self._condition.notify_all()
            return self._snapshot_unlocked()

    def _sync_sound_unlocked(self) -> None:
        self._set_sound_actual_unlocked(self._manual_sound or self._timer_sound)

    def _sync_gas_gun_unlocked(self) -> None:
        self._set_gas_gun_actual_unlocked(self._manual_gas_gun or self._timer_gas_gun)

    def _set_sound_actual_unlocked(self, enabled: bool) -> None:
        if self.sound == enabled:
            return

        if enabled:
            self._require_operational_unlocked()
            self._client.set_relay(1, True)
            self._client.set_volume(100)
            if not self._sound_started:
                self._client.start_sound(self._sound_file_id)
                self._sound_started = True
        else:
            # The T21 has no pause/resume API. Muting keeps playback moving and
            # avoids restarting when sound is enabled again.
            self._client.set_volume(0)
            self._client.set_relay(1, False)
        self.sound = enabled

    def _set_gas_gun_actual_unlocked(self, enabled: bool) -> None:
        if self.gas_gun == enabled:
            return
        if enabled:
            self._require_operational_unlocked()
        self._client.set_relay(2, enabled)
        self.gas_gun = enabled

    def _require_daylight_unlocked(self) -> None:
        if not self._is_daylight_unlocked():
            sunrise, sunset = mackay_daylight_window(self._now_provider())
            raise RuntimeError(
                "Unit is outside Mackay daylight hours "
                f"({sunrise.strftime('%H:%M')} to {sunset.strftime('%H:%M')} AEST)"
            )

    def _require_operational_unlocked(self) -> None:
        self._require_daylight_unlocked()
        if not self.unit_on:
            raise RuntimeError("Unit is off")

    def _is_daylight_unlocked(self) -> bool:
        return is_mackay_daylight(self._now_provider())

    def _daylight_status_unlocked(self) -> dict[str, Any]:
        sunrise, sunset = mackay_daylight_window(self._now_provider())
        return {
            "daylight": self._is_daylight_unlocked(),
            "sunrise": sunrise.strftime("%H:%M"),
            "sunset": sunset.strftime("%H:%M"),
        }

    def _enforce_daylight_unlocked(self) -> None:
        if not self._is_daylight_unlocked() and self.unit_on:
            self._force_unit_off_unlocked()

    def _force_unit_off_unlocked(self) -> None:
        self.unit_on = False
        self.random_timer = False
        self._manual_sound = False
        self._manual_gas_gun = False
        self._timer_sound = False
        self._timer_gas_gun = False
        self._sync_sound_unlocked()
        self._sync_gas_gun_unlocked()

    def _daylight_loop(self) -> None:
        while True:
            with self._condition:
                self._enforce_daylight_unlocked()
                self._condition.notify_all()
                self._condition.wait(timeout=30)

    def _timer_loop(self) -> None:
        while True:
            try:
                self._wait_for_next_random_activation()
                self._run_random_activation()
            except Exception as exc:  # pragma: no cover - hardware failure path.
                with self._condition:
                    self.last_error = str(exc)
                    self.random_timer = False
                    self._timer_sound = False
                    self._timer_gas_gun = False
                    self._sync_sound_unlocked()
                    self._sync_gas_gun_unlocked()
                    self._condition.notify_all()

    def _wait_for_next_random_activation(self) -> None:
        with self._condition:
            while not self.random_timer:
                self._condition.wait()

            average = self.average_interval_minutes * 60
            wait_seconds = random.uniform(average * 0.5, average * 1.5)
            end_at = time.monotonic() + wait_seconds
            while self.random_timer:
                remaining = end_at - time.monotonic()
                if remaining <= 0:
                    return
                self._condition.wait(timeout=remaining)

    def _run_random_activation(self) -> None:
        with self._condition:
            if not self.random_timer:
                return
            mode = random.choice(("before", "during", "after"))
            sound_seconds = random.uniform(TIMER_SOUND_MIN_SECONDS, TIMER_SOUND_MAX_SECONDS)

        if mode == "before":
            self._pulse_timer_gas_gun()
            if not self._sleep_while_timer_enabled(random.uniform(0.5, 2.0)):
                return
            self._play_timer_sound_window(sound_seconds)
        elif mode == "after":
            self._play_timer_sound_window(sound_seconds)
            if not self._sleep_while_timer_enabled(random.uniform(0.5, 2.0)):
                return
            self._pulse_timer_gas_gun()
        else:
            if not self._set_timer_sound(True):
                return
            offset = random.uniform(1.0, max(1.0, sound_seconds - TIMER_GAS_GUN_SECONDS))
            if not self._sleep_while_timer_enabled(offset):
                self._set_timer_sound(False)
                return
            self._pulse_timer_gas_gun()
            remaining = max(0.0, sound_seconds - offset - TIMER_GAS_GUN_SECONDS)
            self._sleep_while_timer_enabled(remaining)
            self._set_timer_sound(False)

    def _play_timer_sound_window(self, seconds: float) -> None:
        if not self._set_timer_sound(True):
            return
        self._sleep_while_timer_enabled(seconds)
        self._set_timer_sound(False)

    def _pulse_timer_gas_gun(self) -> None:
        if not self._set_timer_gas_gun(True):
            return
        self._sleep_while_timer_enabled(TIMER_GAS_GUN_SECONDS)
        self._set_timer_gas_gun(False)

    def _set_timer_sound(self, enabled: bool) -> bool:
        with self._condition:
            if enabled and not self.random_timer:
                return False
            self._timer_sound = enabled
            self._sync_sound_unlocked()
            self._condition.notify_all()
            return self.random_timer or not enabled

    def _set_timer_gas_gun(self, enabled: bool) -> bool:
        with self._condition:
            enabled = enabled and not self.gas_gun_off
            if enabled and not self.random_timer:
                return False
            self._timer_gas_gun = enabled
            self._sync_gas_gun_unlocked()
            self._condition.notify_all()
            return (self.random_timer and enabled) or not enabled

    def _sleep_while_timer_enabled(self, seconds: float) -> bool:
        end_at = time.monotonic() + seconds
        with self._condition:
            while self.random_timer:
                remaining = end_at - time.monotonic()
                if remaining <= 0:
                    return True
                self._condition.wait(timeout=remaining)
            return False


LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#14211b">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="ISAAC1">
  <meta name="apple-mobile-web-app-status-bar-style" content="black">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/icon.svg">
  <title>ISAAC1 Login</title>
  <style>
    * {
      box-sizing: border-box;
    }

    body {
      display: grid;
      min-height: 100vh;
      margin: 0;
      place-items: center;
      background: #f6f7f4;
      color: #14211b;
      font-family: Arial, Helvetica, sans-serif;
    }

    main {
      width: min(420px, calc(100vw - 32px));
      padding: 28px;
      border: 1px solid #d9ded7;
      border-radius: 8px;
      background: #fff;
    }

    h1 {
      margin: 0 0 22px;
      font-size: 28px;
      line-height: 1.1;
      letter-spacing: 0;
    }

    label {
      display: block;
      margin: 16px 0 6px;
      color: #607067;
      font-size: 14px;
      font-weight: 700;
    }

    input {
      width: 100%;
      height: 48px;
      border: 1px solid #aeb8b1;
      border-radius: 8px;
      padding: 0 12px;
      font-size: 18px;
    }

    button {
      width: 100%;
      height: 54px;
      margin-top: 22px;
      border: 0;
      border-radius: 8px;
      background: #14844a;
      color: #fff;
      font-size: 18px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: inset 0 -4px 0 rgba(0, 0, 0, 0.18);
    }

    .error {
      min-height: 22px;
      margin: 0 0 10px;
      color: #b52626;
      font-size: 14px;
      font-weight: 700;
    }
  </style>
</head>
<body>
  <main>
    <h1>ISAAC1</h1>
    <p class="error">{error}</p>
    <form method="post" action="/login">
      <label for="username">Username</label>
      <input id="username" name="username" autocomplete="username" autocapitalize="none" required>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Log in</button>
    </form>
  </main>
</body>
</html>
"""


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#14211b">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="ISAAC1">
  <meta name="apple-mobile-web-app-status-bar-style" content="black">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/icon.svg">
  <title>ISAAC1 Control</title>
  <style>
    :root {
      --bg: #f6f7f4;
      --ink: #14211b;
      --muted: #607067;
      --line: #d9ded7;
      --off: #14844a;
      --off-dark: #0c6336;
      --on: #cf2f2f;
      --on-dark: #9f1f1f;
      --panel: #ffffff;
      --focus: #1d5fd1;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
    }

    main {
      width: min(1040px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 36px 0;
    }

    header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 24px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }

    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.15;
      font-weight: 700;
      letter-spacing: 0;
    }

    #status {
      min-height: 22px;
      color: var(--muted);
      font-size: 14px;
      text-align: right;
    }

    .logout {
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 14px;
      background: var(--panel);
      color: var(--ink);
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
    }

    .controls {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 16px;
      padding-top: 28px;
    }

    button.control {
      width: 100%;
      min-height: 152px;
      border: 0;
      border-radius: 8px;
      color: #fff;
      font-size: 26px;
      font-weight: 700;
      letter-spacing: 0;
      cursor: pointer;
      box-shadow: inset 0 -5px 0 rgba(0, 0, 0, 0.18);
      transition: background-color 120ms ease, transform 120ms ease, box-shadow 120ms ease;
    }

    button.control[data-active="false"] {
      background: var(--off);
    }

    button.control[data-active="false"]:hover {
      background: var(--off-dark);
    }

    button.control[data-active="true"] {
      background: var(--on);
    }

    button.control[data-active="true"]:hover {
      background: var(--on-dark);
    }

    button.control:focus-visible,
    button.step:focus-visible {
      outline: 4px solid var(--focus);
      outline-offset: 4px;
    }

    button.control:active,
    button.step:active {
      transform: translateY(2px);
      box-shadow: inset 0 -3px 0 rgba(0, 0, 0, 0.2);
    }

    button.control:disabled,
    button.step:disabled {
      cursor: wait;
      opacity: 0.72;
    }

    .interval {
      display: grid;
      grid-template-columns: auto minmax(140px, 1fr) auto;
      align-items: center;
      gap: 12px;
      width: min(420px, 100%);
      margin-top: 24px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }

    .counter {
      text-align: center;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }

    .counter span {
      display: block;
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }

    button.step {
      width: 58px;
      height: 58px;
      border: 0;
      border-radius: 8px;
      background: #24382e;
      color: #fff;
      font-size: 24px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: inset 0 -4px 0 rgba(0, 0, 0, 0.18);
    }

    @media (max-width: 900px) {
      .controls {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 620px) {
      header {
        align-items: start;
        flex-direction: column;
      }

      #status {
        text-align: left;
      }

      .controls {
        grid-template-columns: 1fr;
      }

      button.control {
        min-height: 118px;
        font-size: 24px;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>ISAAC1 Control</h1>
      <div>
        <div id="status" role="status" aria-live="polite">Connecting</div>
        <form method="post" action="/logout">
          <button class="logout" type="submit">Logout</button>
        </form>
      </div>
    </header>
    <section class="controls" aria-label="Hardware controls">
      <button class="control" id="unitOn" type="button" data-active="false">On/Off</button>
      <button class="control" id="sound" type="button" data-active="false">Sound</button>
      <button class="control" id="gasGun" type="button" data-active="false">Gas Gun</button>
      <button class="control" id="randomTimer" type="button" data-active="false">Random timer</button>
      <button class="control" id="gasGunOff" type="button" data-active="false">Gas gun off</button>
    </section>
    <section class="interval" aria-label="Random timer interval">
      <button class="step" id="intervalDown" type="button" aria-label="Decrease average interval">&#9660;</button>
      <div class="counter"><span>Average interval</span><output id="intervalValue">1 min</output></div>
      <button class="step" id="intervalUp" type="button" aria-label="Increase average interval">&#9650;</button>
    </section>
  </main>
  <script>
    const buttons = {
      unitOn: document.getElementById("unitOn"),
      sound: document.getElementById("sound"),
      gasGun: document.getElementById("gasGun"),
      randomTimer: document.getElementById("randomTimer"),
      gasGunOff: document.getElementById("gasGunOff"),
      intervalDown: document.getElementById("intervalDown"),
      intervalUp: document.getElementById("intervalUp")
    };
    const status = document.getElementById("status");
    const intervalValue = document.getElementById("intervalValue");

    function setBusy(isBusy) {
      Object.values(buttons).forEach((button) => {
        button.disabled = isBusy;
      });
    }

    function render(state) {
      buttons.unitOn.dataset.active = String(Boolean(state.unitOn));
      buttons.sound.dataset.active = String(Boolean(state.sound));
      buttons.gasGun.dataset.active = String(Boolean(state.gasGun));
      buttons.randomTimer.dataset.active = String(Boolean(state.randomTimer));
      buttons.gasGunOff.dataset.active = String(Boolean(state.gasGunOff));
      intervalValue.textContent = `${state.averageIntervalMinutes} min`;
      const daylight = state.daylight ? "daylight" : "night";
      status.textContent = state.lastError || `${daylight} | ${state.sunrise}-${state.sunset} AEST`;
    }

    async function request(path) {
      setBusy(true);
      try {
        const response = await fetch(path, { method: "POST" });
        if (response.status === 401) {
          window.location = "/login";
          return;
        }
        const data = await response.json();
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "Command failed");
        }
        render(data.state);
      } catch (error) {
        status.textContent = error.message;
      } finally {
        setBusy(false);
      }
    }

    async function loadState() {
      try {
        const response = await fetch("/api/state");
        if (response.status === 401) {
          window.location = "/login";
          return;
        }
        const data = await response.json();
        render(data.state);
      } catch (error) {
        status.textContent = "Unable to reach control server";
      }
    }

    buttons.unitOn.addEventListener("click", () => request("/api/unit/toggle"));
    buttons.sound.addEventListener("click", () => request("/api/sound/toggle"));
    buttons.gasGun.addEventListener("click", () => request("/api/gas-gun/toggle"));
    buttons.randomTimer.addEventListener("click", () => request("/api/random-timer/toggle"));
    buttons.gasGunOff.addEventListener("click", () => request("/api/gas-gun-off/toggle"));
    buttons.intervalDown.addEventListener("click", () => request("/api/timer/decrease"));
    buttons.intervalUp.addEventListener("click", () => request("/api/timer/increase"));
    loadState();
    setInterval(loadState, 1500);
  </script>
</body>
</html>
"""


def make_handler(
    state: ControlState,
    auth: Optional[AuthManager] = None,
) -> type[BaseHTTPRequestHandler]:
    auth_manager = auth or AuthManager()

    class ControlRequestHandler(BaseHTTPRequestHandler):
        server_version = "ISAAC1Control/0.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/login":
                if self._current_user():
                    self._redirect("/")
                else:
                    self._send_login_page()
                return
            if self.path == "/" or self.path.startswith("/?"):
                if not self._require_page_auth():
                    return
                self._send_html(INDEX_HTML)
                return
            if self.path == "/manifest.webmanifest":
                self._send_bytes(
                    json.dumps(WEB_MANIFEST).encode("utf-8"),
                    "application/manifest+json",
                )
                return
            if self.path == "/icon.svg":
                self._send_bytes(APP_ICON_SVG.encode("utf-8"), "image/svg+xml")
                return
            if self.path == "/api/state":
                if not self._require_api_auth():
                    return
                self._send_json({"ok": True, "state": state.snapshot()})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            try:
                if self.path == "/login":
                    self._handle_login()
                    return
                if self.path == "/logout":
                    self._handle_logout()
                    return
                if not self._require_api_auth():
                    return
                if self.path == "/api/unit/toggle":
                    self._send_json({"ok": True, "state": state.toggle_unit()})
                    return
                if self.path == "/api/sound/toggle":
                    self._send_json({"ok": True, "state": state.toggle_sound()})
                    return
                if self.path == "/api/gas-gun/toggle":
                    self._send_json({"ok": True, "state": state.toggle_gas_gun()})
                    return
                if self.path == "/api/random-timer/toggle":
                    self._send_json({"ok": True, "state": state.toggle_random_timer()})
                    return
                if self.path == "/api/gas-gun-off/toggle":
                    self._send_json({"ok": True, "state": state.toggle_gas_gun_off()})
                    return
                if self.path == "/api/timer/increase":
                    self._send_json(
                        {
                            "ok": True,
                            "state": state.adjust_average_interval(INTERVAL_STEP_MINUTES),
                        }
                    )
                    return
                if self.path == "/api/timer/decrease":
                    self._send_json(
                        {
                            "ok": True,
                            "state": state.adjust_average_interval(-INTERVAL_STEP_MINUTES),
                        }
                    )
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:  # pragma: no cover - exercised manually with hardware.
                self._send_json(
                    {"ok": False, "error": str(exc), "state": state.snapshot()},
                    status=HTTPStatus.BAD_GATEWAY,
                )

        def log_message(self, format: str, *args: object) -> None:
            return

        def _current_user(self) -> Optional[AuthUser]:
            if not auth_manager.enabled:
                return AuthUser("local", "admin", "")
            return auth_manager.current_user(self.headers.get("Cookie", ""))

        def _require_page_auth(self) -> bool:
            if self._current_user():
                return True
            self._send_login_page()
            return False

        def _require_api_auth(self) -> bool:
            user = self._current_user()
            if not user:
                self._send_json(
                    {"ok": False, "error": "Authentication required"},
                    status=HTTPStatus.UNAUTHORIZED,
                )
                return False
            if user.role not in {"admin", "operator"}:
                self._send_json(
                    {"ok": False, "error": "Insufficient permission"},
                    status=HTTPStatus.FORBIDDEN,
                )
                return False
            return True

        def _handle_login(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8", "replace")
            params = urllib.parse.parse_qs(body, keep_blank_values=True)
            username = params.get("username", [""])[0]
            password = params.get("password", [""])[0]
            user = auth_manager.authenticate(username, password)
            if not user:
                self._send_login_page("Invalid username or password", HTTPStatus.UNAUTHORIZED)
                return
            self._redirect("/", cookie=auth_manager.create_session_cookie(user))

        def _handle_logout(self) -> None:
            cookie = (
                auth_manager.clear_session_cookie(self.headers.get("Cookie", ""))
                if auth_manager.enabled
                else ""
            )
            self._redirect("/login", cookie=cookie)

        def _send_login_page(
            self,
            error: str = "",
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            page = LOGIN_HTML.replace("{error}", html.escape(error))
            self._send_bytes(
                page.encode("utf-8"),
                "text/html; charset=utf-8",
                status=status,
            )

        def _redirect(self, location: str, cookie: str = "") -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self._send_bytes(body, "text/html; charset=utf-8")

        def _send_bytes(
            self,
            body: bytes,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(
            self,
            payload: Mapping[str, Any],
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return ControlRequestHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ISAAC1 local control UI.")
    parser.add_argument("--bind", default=DEFAULT_BIND)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--rut-url", default=os.environ.get("ISAAC1_RUT241_URL", DEFAULT_RUT241_URL))
    parser.add_argument("--token-env", default="ISAAC1_CONTROL_TOKEN")
    parser.add_argument("--sound-file-id", type=int, default=DEFAULT_FILE_ID)
    return parser


def run_server(
    bind: str,
    port: int,
    rut_url: str,
    token: str,
    sound_file_id: int = DEFAULT_FILE_ID,
) -> None:
    client = TonmindOverRutClient(rut_url, token)
    state = ControlState(client, sound_file_id=sound_file_id)
    auth = AuthManager.from_env()
    handler = make_handler(state, auth)
    server = ThreadingHTTPServer((bind, port), handler)
    print(f"ISAAC1 control UI running at http://{bind}:{port}")
    server.serve_forever()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env, "")
    if not token:
        parser.error(f"{args.token_env} is required")
    run_server(args.bind, args.port, args.rut_url, token, args.sound_file_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
