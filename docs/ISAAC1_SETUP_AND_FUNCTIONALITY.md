# ISAAC1 Setup And Functionality

This document describes how ISAAC1 is set up, how the deployed system is intended to run, and what each control does.

Do not commit live passwords, router tokens, SSH private keys, SIM details, or user credential files. Keep those in ignored local files or on the deployed server under `/etc/isaac1`.

## 1. System Purpose

ISAAC1 provides a browser-based control interface for a field installation containing:

- a Teltonika RUT241 LTE router,
- a Tonmind SIP-T21 paging adapter,
- relay-controlled external equipment,
- an audio soundtrack stored on the Tonmind device,
- and an AWS Lightsail server that exposes a public HTTPS web app.

The user operates ISAAC1 from a phone or browser. The browser talks to the Lightsail server over HTTPS. The Lightsail server talks to the RUT241 over ZeroTier. The RUT241 then sends local HTTP commands to the Tonmind SIP-T21 on its LAN.

## 2. Current Network Roles

The intended deployed topology is:

```text
User phone/browser
    |
    | HTTPS
    v
AWS Lightsail Ubuntu server
    |
    | ZeroTier private network
    v
Teltonika RUT241
    |
    | Local LAN
    v
Tonmind SIP-T21
```

Important addresses and names used by the project:

| Item | Value |
| --- | --- |
| Public web app hostname | Store in the ignored operational credentials note, not in source code |
| Lightsail instance name | `isaac1-control-01` |
| Lightsail static IP | `3.105.152.60` |
| Lightsail ZeroTier IP | `10.23.48.154` |
| RUT241 ZeroTier IP | `10.23.48.89` |
| RUT241 LAN IP | `192.168.241.1` |
| Tonmind SIP-T21 LAN IP | `192.168.241.200` |
| ZeroTier network ID | `08752e18b1384126` |
| ISAAC1 service port on Lightsail | `127.0.0.1:8765` |

The public internet must not connect directly to port `8765`. Caddy terminates HTTPS on ports `80` and `443`, then proxies to `127.0.0.1:8765`.

## 3. Repository Setup

Clone the repository and enter the project directory:

```powershell
git clone https://github.com/Vigilance0491/ISAAC1.git
cd ISAAC1
```

Create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the project in editable mode:

```powershell
python -m pip install -e ".[dev]"
```

Run tests:

```powershell
python -m pytest
```

Expected result:

```text
13 passed
```

## 4. Files And Directories

| Path | Purpose |
| --- | --- |
| `src/isaac1/rut241.py` | CLI entrypoint and RUT241 diagnostic command. |
| `src/isaac1/control_server.py` | Web UI, authentication, daylight guard, random timer, and hardware command sequencing. |
| `deploy/lightsail/cloud-init.sh` | Initial Lightsail bootstrap script. Installs Python, ZeroTier, creates service user, and creates the systemd service shell. |
| `deploy/lightsail/deploy-local.ps1` | Copies the local repo to Lightsail, installs it, writes the runtime env file, and restarts `isaac1-control.service`. |
| `docs/AWS_LIGHTSAIL_SETUP.md` | Short Lightsail setup checklist. |
| `docs/RUT241_FIRST_STEP.md` | RUT241 field setup checklist. |
| `.env.example` | Placeholder local environment variables. Do not put real secrets in this file. |
| `secrets/` | Ignored local-only operational credentials. Do not commit. |

## 5. Local Diagnostic Commands

Run the RUT241 diagnostic command after SSH access to the router is configured:

```powershell
python -m isaac1 rut241-check --host 192.168.241.1 --user root
```

The command checks:

- RutOS board details,
- SIM inserted state,
- PIN state,
- mobile operator,
- signal output,
- default route,
- internet ping to `1.1.1.1`.

Use JSON output when a machine-readable result is useful:

```powershell
python -m isaac1 rut241-check --host 192.168.241.1 --user root --json
```

## 6. Local Control UI For Development

The control UI requires a router-side control token. Do not hard-code the token.

Set the token only in the shell session:

```powershell
$env:ISAAC1_CONTROL_TOKEN = "<router-control-token>"
python -m isaac1 control-ui --rut-url http://10.23.48.89
```

The local app defaults to:

- bind address: `127.0.0.1`,
- port: `8765`,
- RUT URL: `http://10.23.48.89`,
- sound file ID: `20`.

For development without public login, authentication is disabled unless `ISAAC1_AUTH_USERS_FILE` is set.

## 7. RUT241 Setup

The RUT241 should be configured before the Tonmind is left connected to the field LAN.

Minimum setup:

1. Connect the PC to the RUT241 Ethernet/LAN port.
2. Set the RUT241 LAN IP to `192.168.241.1/24`.
3. Enable DHCP on the RUT241 LAN if needed.
4. Configure the WAN port as LAN if the Tonmind must connect there.
5. Confirm the SIM is inserted and operational.
6. Confirm the LTE operator and signal strength.
7. Confirm internet routing works from the RUT241.
8. Install/join ZeroTier on the RUT241.
9. Authorize the RUT241 in ZeroTier Central.
10. Confirm the RUT241 has the ZeroTier IP `10.23.48.89`.
11. Install the ISAAC1 CGI wrapper endpoints on the RUT241.
12. Store the control token on the RUT241 in a file outside the repo.

The RUT241 must not expose raw WebUI or SSH directly to the public internet.

## 8. Tonmind SIP-T21 Setup

The Tonmind SIP-T21 should use a known LAN address:

```text
192.168.241.200
```

The Tonmind is connected to the RUT241 LAN. The RUT241 forwards ISAAC1 commands to the Tonmind from its local network.

Expected Tonmind roles:

- Relay 1: audio amplifier power.
- Relay 2: gas gun control.
- Audio file: soundtrack stored on the Tonmind.

The Tonmind audio file used by ISAAC1 is selected by `--sound-file-id`, defaulting to `20`.

## 9. RUT241 HTTP Wrapper Endpoints

The Lightsail web app does not call the Tonmind directly. It calls authenticated CGI wrapper endpoints on the RUT241:

```text
GET /cgi-bin/custom/isaac1-relay?relay=<1|2>&action=<on|off>&token=<token>
GET /cgi-bin/custom/isaac1-audio?action=volume&volume=<0-100>&token=<token>
GET /cgi-bin/custom/isaac1-audio?action=start&fileid=<file-id>&token=<token>
GET /cgi-bin/custom/isaac1-input?token=<token>
```

The wrapper endpoints should:

- validate the token,
- reject missing or invalid tokens,
- send the corresponding local command to the Tonmind SIP-T21,
- return JSON,
- avoid logging token values.

The input endpoint should return the RUT241 digital input state as JSON:

```json
{"ok": true, "state": "HIGH"}
```

Valid input states are:

- `HIGH`: normal or recovered battery condition.
- `LOW`: low-battery alarm active.
- `UNKNOWN`: input state could not be confirmed.

ISAAC1 treats `UNKNOWN` conservatively. If the low-battery override is already active and the input becomes `UNKNOWN`, the override remains active until `HIGH` is confirmed.

Expected safe reachability test:

```bash
curl http://10.23.48.89/cgi-bin/custom/isaac1-relay
```

An unauthenticated request should return an authorization error. That still confirms the RUT241 is reachable over ZeroTier.

## 10. AWS Lightsail Setup

The Lightsail server replaces the need to leave a Windows PC running.

Provisioning target:

- provider: AWS Lightsail,
- region: Sydney, `ap-southeast-2`,
- image: Ubuntu LTS,
- bundle: 1 GB Linux,
- instance name: `isaac1-control-01`,
- static IP: attached to the instance,
- ZeroTier network: `08752e18b1384126`.

During instance creation, paste `deploy/lightsail/cloud-init.sh` into the launch script field.

After boot:

```bash
sudo zerotier-cli info
sudo zerotier-cli listnetworks
```

Authorize the Lightsail node in ZeroTier Central. Confirm it receives `10.23.48.154` or update operational notes if ZeroTier assigns a different IP.

## 11. Lightsail Firewall

Required public firewall rules:

| Port | Protocol | Purpose |
| --- | --- | --- |
| `22` | TCP | SSH administration. Restrict to trusted IPs where practical. |
| `80` | TCP | HTTP challenge and redirect to HTTPS. |
| `443` | TCP | Public HTTPS web app. |
| `9993` | UDP | ZeroTier peer traffic. |

Do not open TCP `8765` publicly.

## 12. Deploying ISAAC1 To Lightsail

The deploy script copies project files, installs the package, writes `/etc/isaac1/isaac1.env`, and restarts the service.

From PowerShell:

```powershell
cd $env:USERPROFILE\OneDrive\Projects\ISAAC1
$env:ISAAC1_CONTROL_TOKEN = "<router-control-token>"
.\deploy\lightsail\deploy-local.ps1 `
  -ServerHost <lightsail-static-ip> `
  -SshKey <path-to-lightsail-private-key> `
  -AuthUsersFile "/etc/isaac1/users.json" `
  -CookieSecure $true `
  -SessionTtlSeconds 43200
```

Notes:

- `ISAAC1_CONTROL_TOKEN` is written to `/etc/isaac1/isaac1.env` on the server.
- The token must not be committed to Git.
- The server process runs as the `isaac1` system user.
- The app binds only to `127.0.0.1:8765`.
- Caddy exposes the app publicly over HTTPS.

## 13. User Authentication

Public authentication is enabled when this environment variable is present:

```text
ISAAC1_AUTH_USERS_FILE=/etc/isaac1/users.json
```

The users file contains usernames, roles, and password hashes. It should be readable by the service user and not world-readable:

```bash
sudo chgrp isaac1 /etc/isaac1/users.json
sudo chmod 640 /etc/isaac1/users.json
```

Supported roles:

- `admin`,
- `operator`.

Both roles can currently operate the control buttons.

Session behavior:

- default cookie name: `isaac1_session`,
- default session length: 12 hours,
- production cookies should be secure with `ISAAC1_COOKIE_SECURE=true`.

## 14. Caddy HTTPS Reverse Proxy

Caddy should listen publicly on `80` and `443`, then proxy to the local Python service:

```caddyfile
{
    key_type rsa2048
}

<public-hostname> {
    encode gzip
    reverse_proxy 127.0.0.1:8765
}
```

Using `key_type rsa2048` keeps the Let's Encrypt certificate compatible with more iPhone/Safari configurations.

Verify Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl status caddy --no-pager
```

Verify the public endpoint:

```powershell
curl.exe -sS --max-time 20 -o NUL -w "%{http_code} %{ssl_verify_result}`n" https://<public-hostname>/login
```

Expected result:

```text
200 0
```

## 15. Phone Setup

The phone does not need ZeroTier when using the public HTTPS Lightsail deployment. It only needs Safari or another browser with access to the public ISAAC1 HTTPS URL.

### Use ISAAC1 In Safari

1. Open Safari on the iPhone.
2. Go to the ISAAC1 public HTTPS URL.
3. Log in with an operator or admin account.
4. Use the control buttons directly in Safari.

### Add ISAAC1 As An iPhone Web App

Safari can save ISAAC1 to the Home Screen so it opens and behaves like an app.

1. Open Safari on the iPhone.
2. Go to the ISAAC1 public HTTPS URL.
3. Tap the More button, then tap Share.
4. If the Safari tabs layout is Bottom or Top, tap the Share button instead.
5. Scroll down the list of options and tap Add to Home Screen.
6. If Add to Home Screen is not visible, scroll to the bottom, tap Edit Actions, then add Add to Home Screen.
7. Turn on Open as Web App.
8. Name it `ISAAC1`.
9. Tap Add.
10. Open ISAAC1 from the new Home Screen icon.

If Safari cannot establish a secure connection:

- confirm the full URL begins with `https://`,
- confirm iPhone date/time is automatic,
- try mobile data instead of Wi-Fi,
- temporarily disable phone VPN/content filtering,
- confirm Caddy has a valid RSA Let's Encrypt certificate.

## 16. Control Buttons

The web app shows these controls:

| Button | Behavior |
| --- | --- |
| On/Off | Enables or disables the unit, subject to Mackay daylight hours and the low-battery override. Grey means off. Green means on. Grey flashing means low-battery override active. |
| Sound | Turns relay 1 on, sets volume to 100, and starts the configured Tonmind sound file if it has not already been started. Turning it off sets volume to 0 and turns relay 1 off. |
| Gas Gun | Manually toggles relay 2. |
| Random timer | Enables automated random sound and gas-gun activations. |
| Gas gun off | Prevents gas gun activations during timer mode. |
| Average interval arrows | Adjust the average random interval in one-minute increments. |

Button color convention:

- green means off/inactive,
- red means on/active.

The On/Off button has its own color rule:

- grey means off,
- green means on,
- grey flashing with `LOW BATTERY` means RUT241 low-battery override is active and On/Off operation is disabled.

## 17. Low-Battery Override

The RUT241 digital input is wired so that:

- `LOW` means low-battery alarm active,
- `HIGH` means normal or recovered.

ISAAC1 polls the RUT241 input provider using `get_input_state()`. The production provider reads the RUT241 wrapper endpoint configured by `ISAAC1_RUT241_INPUT_PATH`, defaulting to:

```text
/cgi-bin/custom/isaac1-input
```

The polling interval is controlled by `ISAAC1_INPUT_POLL_SECONDS`, defaulting to 5 seconds.

Low-battery state machine:

| State | Meaning |
| --- | --- |
| `NORMAL` | No low-battery override. On/Off behaves normally. |
| `LOW_BATTERY_OVERRIDE` | Input is confirmed `LOW`; On/Off is forced grey/flashing and disabled. |
| `UNKNOWN_WHILE_LOW` | Input became `UNKNOWN` after a confirmed `LOW`; override remains active until `HIGH` is confirmed. |

When `LOW` is detected:

1. ISAAC1 saves the current On/Off button state once for that LOW event.
2. ISAAC1 forces the unit off.
3. The On/Off button label changes to `LOW BATTERY`.
4. The On/Off button becomes grey and flashes.
5. Normal On/Off operation is blocked.

Repeated `LOW` readings do not overwrite the saved state or stack additional flashing effects.

When `HIGH` is confirmed:

1. ISAAC1 clears the low-battery override.
2. The flashing style is removed.
3. The saved On/Off state is restored.
4. Normal On/Off operation is restored.

If communication fails or the input state is `UNKNOWN`, ISAAC1 logs the issue. If a low-battery override is already active, ISAAC1 keeps the safe grey/flashing state and does not restore normal operation until `HIGH` is confirmed.

## 18. Sound Behavior

Relay 1 is tied to sound because relay 1 powers the audio amplifier.

When Sound is turned on:

1. Relay 1 turns on.
2. Tonmind volume is set to `100`.
3. The configured sound file starts if it has not already started during this server process.

When Sound is turned off:

1. Tonmind volume is set to `0`.
2. Relay 1 turns off.

The Tonmind control API used here has start and volume commands, not a true pause/resume command. ISAAC1 therefore approximates pause/resume by muting/unmuting rather than restarting the audio every time.

## 19. Gas Gun Behavior

Relay 2 controls the gas gun.

Manual Gas Gun behavior:

- pressing Gas Gun turns relay 2 on,
- pressing Gas Gun again turns relay 2 off.

Timer-mode Gas Gun behavior:

- relay 2 turns on for 2 seconds per activation,
- Gas gun off prevents timer-mode gas-gun pulses,
- manual gas-gun control is separate from the timer suppression button.

## 20. Random Timer Behavior

The random timer runs only when:

- the unit is on,
- the current Mackay time is between sunrise and sunset,
- Random timer is active.

Timing rules:

- the average interval is stored in minutes,
- minimum average interval: 1 minute,
- maximum average interval: 60 minutes,
- adjustment step: 1 minute,
- actual wait time is randomized between 50% and 150% of the average interval,
- sound activations last randomly between 15 and 30 seconds,
- gas-gun pulses last 2 seconds,
- gas gun may fire before, during, or after the sound window.

If a timer command fails, ISAAC1 records the error and disables the random timer.

## 21. Daylight And Location Guard

ISAAC1 is configured for Mackay, Queensland:

```text
Latitude: -21.1411
Longitude: 149.1860
Timezone: AEST, UTC+10
```

The software calculates sunrise and sunset for the current date using the day of year. This means the permitted on/off window changes through the year.

Queensland does not use daylight saving, so fixed AEST is appropriate.

The unit cannot be turned on outside the daylight window. If the unit is already on and the time moves outside the daylight window, ISAAC1 turns the unit off.

## 22. API Routes

The browser talks to these local server routes:

| Route | Method | Purpose |
| --- | --- | --- |
| `/login` | `GET` | Show login form. |
| `/login` | `POST` | Create authenticated session. |
| `/logout` | `POST` | Clear authenticated session. |
| `/` | `GET` | Control UI. |
| `/api/state` | `GET` | Return current control state. |
| `/api/unit/toggle` | `POST` | Toggle unit on/off. |
| `/api/sound/toggle` | `POST` | Toggle sound/amplifier. |
| `/api/gas-gun/toggle` | `POST` | Toggle relay 2 manually. |
| `/api/random-timer/toggle` | `POST` | Toggle random timer. |
| `/api/gas-gun-off/toggle` | `POST` | Toggle timer gas-gun suppression. |
| `/api/timer/increase` | `POST` | Increase average timer interval. |
| `/api/timer/decrease` | `POST` | Decrease average timer interval. |
| `/manifest.webmanifest` | `GET` | Web app manifest for phone home-screen installation. |
| `/icon.svg` | `GET` | Web app icon. |

When auth is enabled, API calls without a valid session return:

```json
{"ok": false, "error": "Authentication required"}
```

## 23. Service Checks

On Lightsail:

```bash
sudo systemctl status isaac1-control --no-pager
sudo systemctl status caddy --no-pager
sudo zerotier-cli listnetworks
```

Check local app binding:

```bash
sudo ss -ltnp | grep 8765
```

Expected:

```text
127.0.0.1:8765
```

Check public login:

```bash
curl -I https://<public-hostname>/login
```

Check that direct public app access is blocked:

```powershell
curl.exe -sS -m 6 -o NUL -w "%{http_code}`n" http://<lightsail-static-ip>:8765/
```

Expected:

```text
000
```

## 24. Updating The Software

Normal update workflow:

1. Make and test changes locally.
2. Run `python -m pytest`.
3. Commit only source, docs, tests, config examples, and deployment scripts.
4. Push to GitHub.
5. Deploy from the trusted workstation using `deploy/lightsail/deploy-local.ps1`.
6. Confirm `isaac1-control.service` restarted.
7. Confirm the public HTTPS login and authenticated API still work.

Do not commit:

- `.env`,
- `secrets/`,
- `.pytest_cache/`,
- `.venv/`,
- logs,
- generated spreadsheets,
- generated PDFs,
- SSH keys,
- router tokens,
- private operational data.

## 25. GitHub

The project repository is:

```text
https://github.com/Vigilance0491/ISAAC1
```

Current branch:

```text
main
```

## 26. Known Limitations

- Sound stop/resume is implemented through volume mute/unmute and relay 1 control, because the currently used Tonmind command path does not provide a true pause/resume primitive.
- User accounts are file-based on the server rather than managed through an admin UI.
- The random timer state is in memory. Restarting the service resets in-memory state.
- Daylight calculation is hard-coded for Mackay, QLD.
- Hardware commands depend on the RUT241 wrapper endpoints and Tonmind LAN reachability.

## 27. Operational Safety Notes

- Keep gas-gun relay wiring fail-safe.
- Confirm relay polarity and Tonmind relay behavior before connecting real equipment.
- Keep the RUT241 and Tonmind admin passwords out of Git.
- Restrict SSH where practical.
- Keep `8765` private.
- Rotate public web passwords if they are exposed.
- Rotate the RUT241 control token if it is exposed.
- Review AWS security groups/Lightsail firewall after each infrastructure change.
