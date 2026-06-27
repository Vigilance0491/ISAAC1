# GitHub Setup

GitHub CLI was not available when this workspace was prepared, and no remote is currently configured.

## Create the GitHub repository later

1. Create a new empty GitHub repository named `ISAAC1`.
2. Keep it empty. Do not add a README, `.gitignore`, or license on GitHub.
3. Copy the new repository URL.
4. In PowerShell, from this project folder, add the remote and push:

```powershell
cd $env:USERPROFILE\OneDrive\Projects\ISAAC1
git remote add origin <ISAAC1_REPO_URL>
git remote -v
git push -u origin main
```

Do not use the old `Inferance1` remote. ISAAC1 must have its own repository URL.
