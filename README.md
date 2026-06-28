# ISAAC1

ISAAC1 is a new, separate Python project.

This repository is intentionally independent from the OneSchool timetable project. It does not contain OneSchool code, data, reports, logs, workbooks, PDFs, browser profiles, credentials, or live test output.

ISAAC1's target system is a Teltonika RUT241 controlling a Tonmind SIP-T21 paging adapter over the internet. The first milestone is to configure and verify the RUT241 over Ethernet so it can be managed remotely before its LAN connection is handed to the SIP-T21.

## Project status

ISAAC1 is in initial setup. The current scaffold is ready for requirements and prototype planning.

## Getting started

Open PowerShell and enter the project folder:

```powershell
cd $env:USERPROFILE\OneDrive\Projects\ISAAC1
```

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the project in editable mode with development tools:

```powershell
python -m pip install -e ".[dev]"
```

Run tests:

```powershell
python -m pytest
```

Run the package:

```powershell
python -m isaac1
```

Run the first RUT241 diagnostic check after SSH access is configured:

```powershell
python -m isaac1 rut241-check --host 192.168.1.1 --user root
```

Run the local control UI after `ISAAC1_CONTROL_TOKEN` is set:

```powershell
python -m isaac1 control-ui --rut-url http://10.23.48.89
```

For the always-on cloud deployment, see [docs/AWS_LIGHTSAIL_SETUP.md](docs/AWS_LIGHTSAIL_SETUP.md).

See [docs/RUT241_FIRST_STEP.md](docs/RUT241_FIRST_STEP.md) for the field setup checklist.
