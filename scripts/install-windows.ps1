[CmdletBinding()]
param(
    [string]$AdminEmail = $(if ($env:SIO_INSTALL_ADMIN_EMAIL) { $env:SIO_INSTALL_ADMIN_EMAIL } else { "admin@example.com" }),
    [string]$AdminPassword = $env:SIO_INSTALL_ADMIN_PASSWORD,
    [string]$WorkspaceName = $(if ($env:SIO_INSTALL_WORKSPACE_NAME) { $env:SIO_INSTALL_WORKSPACE_NAME } else { "Sports Intelligence OS" }),
    [switch]$WithDemoData,
    [switch]$SkipDockerInstall,
    [switch]$SkipBootstrap,
    [ValidateRange(30, 1800)]
    [int]$WaitSeconds = $(if ($env:SIO_INSTALL_WAIT_SECONDS) { [int]$env:SIO_INSTALL_WAIT_SECONDS } else { 300 })
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"
$StateDirectory = Join-Path $ProjectRoot ".sio"
$StateFile = Join-Path $StateDirectory "install-state.json"
$RuleFile = "/workspace/data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function New-RandomBytes {
    param([Parameter(Mandatory = $true)][int]$Count)
    $bytes = New-Object byte[] $Count
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return $bytes
}

function New-HexSecret {
    param([Parameter(Mandatory = $true)][int]$ByteCount)
    return -join ((New-RandomBytes -Count $ByteCount) | ForEach-Object { $_.ToString("x2") })
}

function New-UrlSafeKey {
    $base64 = [Convert]::ToBase64String((New-RandomBytes -Count 32))
    return $base64.Replace("+", "-").Replace("/", "_")
}

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [AllowEmptyString()][string]$Value
    )
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $Path) {
        [System.IO.File]::ReadAllLines($Path) | ForEach-Object { [void]$lines.Add($_) }
    }
    $prefix = "$Key="
    $replaced = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index].StartsWith($prefix, [StringComparison]::Ordinal)) {
            $lines[$index] = "$prefix$Value"
            $replaced = $true
        }
    }
    if (-not $replaced) {
        [void]$lines.Add("$prefix$Value")
    }
    [System.IO.File]::WriteAllLines($Path, $lines, $script:Utf8NoBom)
}

function Invoke-Docker {
    $Arguments = @($args)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Test-DockerDaemon {
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $knownDockerPaths = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"),
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin")
    ) | Where-Object { Test-Path -LiteralPath $_ }
    $env:Path = (@($machinePath, $userPath) + $knownDockerPaths | Where-Object { $_ }) -join ";"
}

function Start-DockerDesktop {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe")
    )
    $executable = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $executable) {
        throw "Docker Desktop was installed, but its executable could not be found. Restart Windows and rerun the installer."
    }

    Write-Host "Starting Docker Desktop. Complete any visible first-run terms or WSL prompt..."
    # Docker Desktop is intentionally visible: the user may need to accept its terms.
    Start-Process -FilePath $executable | Out-Null
}

Push-Location $ProjectRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        if ($SkipDockerInstall) {
            throw "Docker is missing and -SkipDockerInstall was provided."
        }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "winget is unavailable. Install Docker Desktop manually from https://docs.docker.com/desktop/setup/install/windows-install/ and rerun with -SkipDockerInstall."
        }

        Write-Host "Installing Docker Desktop with Windows Package Manager..."
        & winget install --exact --id Docker.DockerDesktop --source winget --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Desktop installation failed with exit code $LASTEXITCODE. A Windows or WSL restart may be required."
        }
        Refresh-ProcessPath
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Refresh-ProcessPath
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is unavailable after installation. Restart Windows, then rerun this script with -SkipDockerInstall."
    }

    if (-not (Test-DockerDaemon)) {
        Start-DockerDesktop
        $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
        while (-not (Test-DockerDaemon)) {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Docker Desktop did not become ready within $WaitSeconds seconds. Complete its first-run/WSL setup or restart Windows, then rerun this installer."
            }
            Start-Sleep -Seconds 3
        }
    }

    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is required, but 'docker compose version' failed."
    }

    $createdEnv = $false
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination $EnvFile
        $postgresPassword = New-HexSecret -ByteCount 24
        Set-DotEnvValue -Path $EnvFile -Key "POSTGRES_PASSWORD" -Value $postgresPassword
        Set-DotEnvValue -Path $EnvFile -Key "SIO_DATABASE_URL" -Value "postgresql+asyncpg://sio:$postgresPassword@127.0.0.1:5432/sports_intelligence"
        Set-DotEnvValue -Path $EnvFile -Key "SIO_SECRET_KEY" -Value (New-HexSecret -ByteCount 48)
        Set-DotEnvValue -Path $EnvFile -Key "SIO_NOTIFICATION_ENCRYPTION_KEY" -Value (New-UrlSafeKey)
        $createdEnv = $true
        Write-Host "Created .env with random local secrets. The file is excluded from Git."
    }
    else {
        Write-Host "Preserving the existing .env file without rotating credentials."
    }

    if (-not $createdEnv) {
        $weakPassword = Select-String -LiteralPath $EnvFile -SimpleMatch "POSTGRES_PASSWORD=sio-local-development-only" -Quiet
        if ($weakPassword) {
            Write-Warning "The existing .env still contains the development database password."
        }
    }

    Write-Host "Validating Docker Compose configuration..."
    Invoke-Docker compose config --quiet
    Write-Host "Building and starting PostgreSQL, Redis, API, Worker, Beat, Web and Caddy..."
    Invoke-Docker compose up -d --build

    Write-Host "Waiting for the API readiness check..."
    $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
    $ready = $false
    while (-not $ready) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 5
            $ready = $response.StatusCode -eq 200
        }
        catch {
            $ready = $false
        }
        if (-not $ready -and [DateTime]::UtcNow -ge $deadline) {
            & docker compose ps
            & docker compose logs --tail=80 api postgres redis
            throw "Services did not become ready within $WaitSeconds seconds."
        }
        if (-not $ready) {
            Start-Sleep -Seconds 3
        }
    }

    New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
    $generatedPassword = $false
    $adminCreated = $false
    if ($SkipBootstrap) {
        Write-Host "Skipping administrator creation as requested."
    }
    elseif (Test-Path -LiteralPath $StateFile) {
        Write-Host "Installer state exists; preserving the existing administrator."
    }
    else {
        if ([string]::IsNullOrWhiteSpace($AdminPassword)) {
            $AdminPassword = "Sio!7$(New-HexSecret -ByteCount 10)"
            $generatedPassword = $true
        }
        Write-Host "Creating the initial administrator and workspace..."
        Invoke-Docker compose run --rm `
            -e "SIO_BOOTSTRAP_ADMIN_EMAIL=$AdminEmail" `
            -e "SIO_BOOTSTRAP_ADMIN_PASSWORD=$AdminPassword" `
            -e "SIO_BOOTSTRAP_WORKSPACE_NAME=$WorkspaceName" `
            api python -m app.cli bootstrap-admin
        $state = [ordered]@{
            installed_at = [DateTime]::UtcNow.ToString("o")
            admin_email = $AdminEmail
        } | ConvertTo-Json
        [System.IO.File]::WriteAllText($StateFile, $state, $Utf8NoBom)
        $adminCreated = $true
    }

    Write-Host "Loading idempotent platform, rule, Prompt, news-source and automation defaults..."
    Invoke-Docker compose run --rm api python -m app.cli seed-platforms
    Invoke-Docker compose run --rm api python -m app.cli import-rules --file $RuleFile
    Invoke-Docker compose run --rm api python -m app.cli seed-generation
    Invoke-Docker compose run --rm api python -m app.cli seed-news-sources
    Invoke-Docker compose run --rm api python -m app.cli seed-automations

    if ($WithDemoData) {
        Write-Host "Adding explicitly labelled DEMO/MOCK monitoring data..."
        Invoke-Docker compose run --rm api python -m app.cli seed-demo-monitoring
    }
    else {
        Write-Host "Demo data was not installed. Use -WithDemoData to opt in to labelled Mock records."
    }

    Write-Host "Verifying all Compose services and the unified web entrypoint..."
    $runningServices = @(& docker compose ps --status running --services)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to query Docker Compose service state."
    }
    foreach ($serviceName in @("postgres", "redis", "api", "worker", "beat", "web", "proxy")) {
        if ($serviceName -notin $runningServices) {
            & docker compose ps
            & docker compose logs --tail=80 $serviceName
            throw "Compose service is not running: $serviceName"
        }
    }

    $webDeadline = [DateTime]::UtcNow.AddSeconds(60)
    $webReady = $false
    while (-not $webReady) {
        try {
            $webResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8080/login" -TimeoutSec 5
            $webReady = $webResponse.StatusCode -eq 200
        }
        catch {
            $webReady = $false
        }
        if (-not $webReady -and [DateTime]::UtcNow -ge $webDeadline) {
            & docker compose logs --tail=80 web proxy
            throw "The unified web entrypoint did not become ready within 60 seconds."
        }
        if (-not $webReady) {
            Start-Sleep -Seconds 3
        }
    }

    Write-Host ""
    Write-Host "Sports Intelligence OS is ready:"
    Write-Host "  Web:    http://localhost:8080"
    Write-Host "  API:    http://127.0.0.1:8000/docs"
    Write-Host "  Health: http://127.0.0.1:8000/health/ready"
    if ($adminCreated) {
        Write-Host "  Admin:  $AdminEmail"
        if ($generatedPassword) {
            Write-Host "  One-time generated password: $AdminPassword"
            Write-Host "Store this password now. It is not written to the repository or installer state."
        }
    }
}
finally {
    Pop-Location
}
