# ISAAC1

ISAAC1 is a new, separate Python project.

This repository is intentionally independent from the OneSchool timetable project. It does not contain OneSchool code, data, reports, logs, workbooks, PDFs, browser profiles, credentials, or live test output.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

