# NEXUS Sentinel — Windows Task Scheduler Installation
# Run as Administrator in PowerShell
#
# Usage: powershell -ExecutionPolicy Bypass -File install_windows_scheduler.ps1

$projectPath = "C:\Users\srila\Claude Workspace\Nexus\Nexus\sentinel"
$pythonExe   = "C:\Users\srila\AppData\Local\Python\bin\python3.exe"
$logsPath    = "$projectPath\logs"

# Ensure logs directory exists
if (!(Test-Path $logsPath)) {
    New-Item -ItemType Directory -Path $logsPath | Out-Null
    Write-Host "[Setup] Created logs directory: $logsPath" -ForegroundColor Green
}

Write-Host "`n[Setup] Installing NEXUS Sentinel tasks to Windows Task Scheduler..." -ForegroundColor Cyan
Write-Host "[Setup] Project: $projectPath" -ForegroundColor Gray
Write-Host "[Setup] Python:  $pythonExe`n" -ForegroundColor Gray

# Helper function to create task
function New-SentinelTask {
    param(
        [string]$TaskName,
        [string]$Hour,
        [string]$Minute,
        [string]$Days,
        [string]$Script,
        [string]$LogFile
    )

    $time = "{0:D2}:{1:D2}:00" -f [int]$Hour, [int]$Minute
    $cmd = "cd `"$projectPath`" && `"$pythonExe`" $Script >> `"$LogFile`" 2>&1"

    try {
        schtasks /create /tn "NEXUS\$TaskName" /tr "powershell -NoProfile -Command `"$cmd`"" `
            /sc DAILY /d $Days /st $time /f /ru $env:USERNAME | Out-Null
        Write-Host "[✓] $TaskName at $time ($Days)" -ForegroundColor Green
    } catch {
        Write-Host "[✗] $TaskName FAILED: $_" -ForegroundColor Red
    }
}

# ── Deep Scans (4x per day, Mon-Fri) ───────────────────────────────────────
Write-Host "`n[DEEP SCANS]" -ForegroundColor Yellow

New-SentinelTask -TaskName "DeepScan-0830-PreMarket" -Hour 8 -Minute 30 -Days "MON,TUE,WED,THU,FRI" `
    -Script "run_scan.py deep" -LogFile "$logsPath\scan.log"

New-SentinelTask -TaskName "DeepScan-0945-PostOpen" -Hour 9 -Minute 45 -Days "MON,TUE,WED,THU,FRI" `
    -Script "run_scan.py deep" -LogFile "$logsPath\scan.log"

New-SentinelTask -TaskName "DeepScan-1100-MidMorning" -Hour 11 -Minute 0 -Days "MON,TUE,WED,THU,FRI" `
    -Script "run_scan.py deep" -LogFile "$logsPath\scan.log"

New-SentinelTask -TaskName "DeepScan-1400-Afternoon" -Hour 14 -Minute 0 -Days "MON,TUE,WED,THU,FRI" `
    -Script "run_scan.py deep" -LogFile "$logsPath\scan.log"

# ── Portfolio Monitor (every 30 min during market hours, 09:30-16:00, Mon-Fri) ──
Write-Host "`n[PORTFOLIO MONITOR — every 30 min, 09:30-16:00]" -ForegroundColor Yellow

$times = @(
    @{h=9; m=30},
    @{h=10; m=0}, @{h=10; m=30},
    @{h=11; m=0}, @{h=11; m=30},
    @{h=12; m=0}, @{h=12; m=30},
    @{h=13; m=0}, @{h=13; m=30},
    @{h=14; m=0}, @{h=14; m=30},
    @{h=15; m=0}, @{h=15; m=30},
    @{h=16; m=0}
)

$times | ForEach-Object {
    $taskName = "PortfolioMonitor-{0:D2}{1:D2}" -f $_.h, $_.m
    New-SentinelTask -TaskName $taskName -Hour $_.h -Minute $_.m -Days "MON,TUE,WED,THU,FRI" `
        -Script "run_scan.py portfolio" -LogFile "$logsPath\portfolio.log"
}

Write-Host "`n[Setup] ✓ All tasks installed!" -ForegroundColor Green
Write-Host "`nTo verify, run: schtasks /query /tn NEXUS /v" -ForegroundColor Cyan
Write-Host "`nTo view logs: Get-Content '$logsPath\scan.log' -Tail 20" -ForegroundColor Gray
Write-Host "`nTo remove all tasks: schtasks /delete /tn NEXUS /f`n" -ForegroundColor Gray
