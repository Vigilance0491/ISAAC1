# Development

## Enter the project folder

```powershell
cd $env:USERPROFILE\OneDrive\Projects\ISAAC1
```

## Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## Install in editable mode

```powershell
python -m pip install -e ".[dev]"
```

## Run tests

```powershell
python -m pytest
```

## Run the package

```powershell
python -m isaac1
```

## Do not commit

- `.env` files or real secrets.
- `.venv/` or other virtual environments.
- `__pycache__/`, `.pytest_cache/`, and other caches.
- Logs, temporary files, generated reports, spreadsheets, PDFs, or private data.
- Any files copied from unrelated projects.
