param(
    [Parameter(Mandatory = $true)]
    [string]$ServerHost,

    [string]$User = "ubuntu",

    [string]$SshKey = "",

    [string]$RutUrl = "http://10.23.48.89",

    [string]$Token = $env:ISAAC1_CONTROL_TOKEN,

    [string]$AuthUsersFile = "",

    [bool]$CookieSecure = $false,

    [int]$SessionTtlSeconds = 43200
)

$ErrorActionPreference = "Stop"

$repoRoot = (& git rev-parse --show-toplevel).Trim()
$repoRootNormalized = $repoRoot.Replace("\", "/")
$expectedRoot = "C:/Users/john/OneDrive/Projects/ISAAC1"
if ($repoRootNormalized -ne $expectedRoot) {
    throw "Refusing to deploy from '$repoRoot'. Expected '$expectedRoot'."
}

if (-not $Token) {
    throw "Set ISAAC1_CONTROL_TOKEN or pass -Token. Do not store the real token in the repo."
}

$target = "$User@$ServerHost"
$knownHosts = Join-Path $env:TEMP "isaac1_lightsail_known_hosts"
$sshArgs = @(
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=$knownHosts",
    "-o",
    "ConnectTimeout=20"
)
if ($SshKey) {
    $sshArgs += @("-i", $SshKey)
}

$release = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "isaac1-deploy-$([guid]::NewGuid().ToString('N'))"
$stage = Join-Path $tempRoot "app"
$archive = Join-Path $tempRoot "isaac1-app.tgz"
$envFile = Join-Path $tempRoot "isaac1.env"

try {
    New-Item -ItemType Directory -Path $stage -Force | Out-Null

    $items = @(
        "README.md",
        "pyproject.toml",
        ".gitignore",
        ".env.example",
        "docs",
        "src",
        "tests"
    )

    foreach ($item in $items) {
        $source = Join-Path $repoRoot $item
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination $stage -Recurse -Force
        }
    }

    tar.exe -czf $archive -C $tempRoot app

    $envText = @"
ISAAC1_RUT241_URL=$RutUrl
ISAAC1_CONTROL_TOKEN=$Token
PYTHONUNBUFFERED=1
"@

    if ($AuthUsersFile) {
        $secureValue = if ($CookieSecure) { "true" } else { "false" }
        $envText = $envText.TrimEnd() + "`n"
        $envText += @"
ISAAC1_AUTH_USERS_FILE=$AuthUsersFile
ISAAC1_COOKIE_SECURE=$secureValue
ISAAC1_SESSION_TTL_SECONDS=$SessionTtlSeconds
"@
    }

    $envText | Set-Content -LiteralPath $envFile -NoNewline -Encoding ascii

    & ssh @sshArgs $target "mkdir -p /tmp/isaac1-deploy"
    & scp @sshArgs $archive "${target}:/tmp/isaac1-deploy/isaac1-app.tgz"
    & scp @sshArgs $envFile "${target}:/tmp/isaac1-deploy/isaac1.env"

    $remoteScript = @"
set -Eeuo pipefail
release="$release"
sudo mkdir -p "/opt/isaac1/releases/`$release" /etc/isaac1
sudo tar -xzf /tmp/isaac1-deploy/isaac1-app.tgz -C "/opt/isaac1/releases/`$release" --strip-components=1
sudo install -m 600 -o root -g root /tmp/isaac1-deploy/isaac1.env /etc/isaac1/isaac1.env
if [ ! -d /opt/isaac1/venv ]; then
  sudo python3 -m venv /opt/isaac1/venv
fi
sudo /opt/isaac1/venv/bin/python -m pip install --upgrade pip setuptools wheel
sudo /opt/isaac1/venv/bin/python -m pip install -e "/opt/isaac1/releases/`$release"
sudo ln -sfn "/opt/isaac1/releases/`$release" /opt/isaac1/app
sudo chown -R isaac1:isaac1 "/opt/isaac1/releases/`$release"
sudo tee /etc/systemd/system/isaac1-control.service >/dev/null <<'EOF'
[Unit]
Description=ISAAC1 control UI
After=network-online.target zerotier-one.service
Wants=network-online.target
Requires=zerotier-one.service

[Service]
Type=simple
User=isaac1
Group=isaac1
WorkingDirectory=/opt/isaac1/app
EnvironmentFile=/etc/isaac1/isaac1.env
ExecStart=/opt/isaac1/venv/bin/python -m isaac1 control-ui --bind 127.0.0.1 --port 8765
Restart=always
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable isaac1-control
sudo systemctl restart isaac1-control
sudo systemctl --no-pager --full status isaac1-control
sudo zerotier-cli listnetworks || true
"@

    ($remoteScript -replace "`r", "") | & ssh @sshArgs $target "bash -s"

    Write-Host "Deployment complete."
    Write-Host "Open the UI over ZeroTier at: http://<lightsail-zerotier-ip>:8765"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
