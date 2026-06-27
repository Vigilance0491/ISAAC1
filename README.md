# ISAAC1

ISAAC1 is a new, separate Python project.

This repository is intentionally independent from the OneSchool timetable project. It does not contain OneSchool code, data, reports, logs, workbooks, PDFs, browser profiles, credentials, or live test output.

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
