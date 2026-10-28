<#
.SYNOPSIS
Resume the local agents after an outage or a manual stop: check that Hinterglass answers, start
`hglab local up` detached (the NemoClaw stack, the status page, A2A and the supervisor), and restore
the logon start. See docs/local-runtime-setup.md, "Stop, and resume after an outage".

.EXAMPLE
pwsh -File scripts\resume-local.ps1
pwsh -File scripts\resume-local.ps1 -NoLogonStart   # run now, but do not start at logon
#>
param(
    [switch]$Force,         # start even though Hinterglass does not answer yet
    [switch]$NoLogonStart,  # leave the logon start removed
    [string]$Distro = "Ubuntu",  # config/local.yaml: nemoclaw.wsl_distro
    [int]$WaitMinutes = 10
)
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$hglab = Join-Path $repo ".venv\Scripts\hglab.exe"
$log = Join-Path $repo "runs\local\up.log"
$supervisorLog = Join-Path $repo "runs\local\supervisor.log"

# 1. Hinterglass answers: its public events page needs no key
try {
    $r = Invoke-WebRequest -Uri "https://hinterglass.com/api/v1/world/events?limit=1" -TimeoutSec 20 -UseBasicParsing
    Write-Output "Hinterglass answers: HTTP $($r.StatusCode)"
} catch {
    if (-not $Force) {
        Write-Output "Hinterglass does not answer yet ($($_.Exception.Message)): nothing started. Try again later, or pass -Force."
        exit 1
    }
    Write-Output "Hinterglass does not answer yet: starting anyway (-Force)"
}

# 2. one supervisor at a time
$running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*-m hglab local up*" }
if ($running) {
    Write-Output ("the supervisor is already running (pid {0}): nothing started" -f ($running.ProcessId -join ", "))
    exit 0
}

# 3. the sandbox's gateway starts with WSL again; `hglab local up` starts it and the sandbox and re-enables the dashboard forward
wsl -d $Distro -e bash -lc "systemctl --user enable nemoclaw-openshell-gateway"

# 4. `hglab local up`, detached and minimised, as the logon start runs it
$started = [datetimeoffset]::UtcNow
Add-Content -Path $log -Value ("`n==== resume requested {0} ====" -f $started.ToString("o"))
$cmd = '/c cd /d "' + $repo + '" && "' + $python + '" -m hglab local up >> "' + $log + '" 2>&1'
Start-Process -FilePath "cmd.exe" -ArgumentList $cmd -WindowStyle Minimized
Write-Output "hglab local up started in a minimised window (log: runs\local\up.log)"

# 5. the logon start
if (-not $NoLogonStart) { & $hglab local service install }

# 6. wait for the supervisor's first line (the NemoClaw stack can take a few minutes), then report
$deadline = $started.AddMinutes($WaitMinutes)
$up = $false
while (-not $up -and [datetimeoffset]::UtcNow -lt $deadline) {
    Start-Sleep -Seconds 10
    if (Test-Path $supervisorLog) {
        foreach ($line in Get-Content $supervisorLog -Tail 50) {
            if ($line -match "^(\S+) supervisor up:" -and [datetimeoffset]::Parse($Matches[1]) -gt $started) { $up = $true }
        }
    }
}
if (-not $up) {
    Write-Output "no 'supervisor up' line after $WaitMinutes minutes: read the end of runs\local\up.log"
    exit 1
}
Write-Output "supervisor up"
& $hglab local status | Select-Object -First 3
& $hglab local stack
