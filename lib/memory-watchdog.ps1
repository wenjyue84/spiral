# memory-watchdog.ps1 - Graduated memory pressure controller
#
# Graduated mode (with -ScratchDir):
#   powershell.exe -ExecutionPolicy Bypass -File lib/memory-watchdog.ps1 \
#     -ScratchDir .spiral -ThresholdMB 2560 -ParentPID 12345 \
#     -ThresholdPct "40,25,15,8" -Hysteresis 2 -IntervalSec 15
#
# Kill-only mode (backwards compatible, no -ScratchDir):
#   powershell.exe -ExecutionPolicy Bypass -File lib/memory-watchdog.ps1 \
#     -ThresholdMB 2560 -ParentPID 12345
#
# Graduated mode: Polls system-wide free RAM, computes pressure level (0-4),
# writes _memory_pressure.json atomically. Only kills processes at level 4.
#
# Kill-only mode: Kills any node.exe process whose Working Set exceeds
# ThresholdMB. Identical to the original watchdog behavior.
#
# Self-terminates when the parent PID exits.

param(
    [int]$ThresholdMB = 2560,
    [int]$ParentPID = 0,
    [int]$IntervalSec = 15,
    [string]$ScratchDir = "",
    [string]$ThresholdPct = "40,25,18,12",
    [int]$Hysteresis = 2,
    [string]$WorkerPIDDir = "",
    [string]$ProtectPIDs = "",
    [int]$PreemptivePressureMB = 0
)

$ThresholdBytes = [int64]$ThresholdMB * 1024 * 1024

# Determine mode
$GraduatedMode = ($ScratchDir -ne "")

if ($GraduatedMode) {
    $LogFile = Join-Path $ScratchDir "_memory_watchdog.log"
    $PressureFile = Join-Path $ScratchDir "_memory_pressure.json"
    $LowPowerFlag = Join-Path $ScratchDir "_low_power_active"
} else {
    $LogFile = Join-Path (Get-Location) ".spiral/_memory_watchdog.log"
}

# Ensure log directory exists
$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $entry = "[$ts] $Message"
    Add-Content -Path $LogFile -Value $entry -ErrorAction SilentlyContinue
}

# Parse threshold percentages (descending: normal, elevated, high, critical)
$Thresholds = $ThresholdPct.Split(',') | ForEach-Object { [int]$_ }
if ($Thresholds.Count -lt 4) {
    # Pad with defaults if fewer than 4 values provided
    while ($Thresholds.Count -lt 4) { $Thresholds += 8 }
}

# Hysteresis state
$ConsecutiveLowerCount = 0
$ReportedLevel = 0

function Get-SystemMemoryInfo {
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $totalMB = [math]::Floor($os.TotalVisibleMemorySize / 1024)
        $freeMB = [math]::Floor($os.FreePhysicalMemory / 1024)
        $freePct = if ($totalMB -gt 0) { [math]::Floor(($freeMB / $totalMB) * 100) } else { 100 }
        return @{ TotalMB = $totalMB; FreeMB = $freeMB; FreePct = $freePct }
    } catch {
        return @{ TotalMB = 0; FreeMB = 99999; FreePct = 100 }
    }
}

function Get-NodeProcessCount {
    try {
        $procs = Get-Process -Name "node" -ErrorAction SilentlyContinue
        if ($null -eq $procs) { return 0 }
        if ($procs -is [array]) { return $procs.Count }
        return 1
    } catch {
        return 0
    }
}

function Get-PressureLevel {
    param([int]$FreePct)
    # Level 4: < threshold[3] (emergency, e.g. <8% free)
    if ($FreePct -lt $Thresholds[3]) { return 4 }
    # Level 3: < threshold[2] (critical, e.g. <15% free)
    if ($FreePct -lt $Thresholds[2]) { return 3 }
    # Level 2: < threshold[1] (high, e.g. <25% free)
    if ($FreePct -lt $Thresholds[1]) { return 2 }
    # Level 1: < threshold[0] (elevated, e.g. <40% free)
    if ($FreePct -lt $Thresholds[0]) { return 1 }
    # Level 0: normal
    return 0
}

function Get-Recommendations {
    param([int]$Level, [int]$FreeMB, [int]$NodeProcs)

    $rec = @{
        recommended_workers = 0
        recommended_model   = ""
        skip_phases         = @()
    }

    switch ($Level) {
        0 {
            # Normal - no restrictions
            # Per-worker budget: ~1536MB (1024 heap + ~512 non-heap overhead)
            $rec.recommended_workers = [math]::Max(1, [math]::Floor(($FreeMB - 512) / 1536))
            $rec.recommended_model = ""
            $rec.skip_phases = @()
        }
        1 {
            # Elevated - brief delays only, no hard restrictions
            $rec.recommended_workers = [math]::Max(1, [math]::Floor(($FreeMB - 512) / 1536))
            $rec.recommended_model = ""
            $rec.skip_phases = @()
        }
        2 {
            # High - reduce workers, cap model at sonnet, skip Phase R
            $rec.recommended_workers = [math]::Max(1, [math]::Min(2, [math]::Floor(($FreeMB - 512) / 1536)))
            $rec.recommended_model = "sonnet"
            $rec.skip_phases = @("R")
        }
        3 {
            # Critical - workers to 1, force haiku, skip R+T, pause excess workers
            $rec.recommended_workers = 1
            $rec.recommended_model = "haiku"
            $rec.skip_phases = @("R", "T")
        }
        4 {
            # Emergency - same as critical + kill largest process
            $rec.recommended_workers = 1
            $rec.recommended_model = "haiku"
            $rec.skip_phases = @("R", "T")
        }
    }

    return $rec
}

function Write-PressureFile {
    param([int]$Level, [int]$FreeMB, [int]$NodeProcs, $Recommendations)

    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

    # Build skip_phases JSON array
    $skipItems = @()
    foreach ($phase in $Recommendations.skip_phases) {
        $skipItems += "`"$phase`""
    }
    $skipJson = $skipItems -join ", "

    $json = @"
{
  "level": $Level,
  "free_mb": $FreeMB,
  "node_procs": $NodeProcs,
  "recommended_workers": $($Recommendations.recommended_workers),
  "recommended_model": "$($Recommendations.recommended_model)",
  "skip_phases": [$skipJson],
  "ts": "$ts"
}
"@

    # Atomic write: write to temp file then rename
    $tmpFile = "$PressureFile.tmp"
    try {
        Set-Content -Path $tmpFile -Value $json -Encoding UTF8 -ErrorAction Stop
        Move-Item -Path $tmpFile -Destination $PressureFile -Force -ErrorAction Stop
    } catch {
        # If rename fails, try direct write as fallback
        Set-Content -Path $PressureFile -Value $json -Encoding UTF8 -ErrorAction SilentlyContinue
        Remove-Item -Path $tmpFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-WorkerPIDs {
    $pids = @()
    if ($WorkerPIDDir -ne "" -and (Test-Path $WorkerPIDDir)) {
        Get-ChildItem -Path $WorkerPIDDir -Recurse -Filter "worker.pid" -ErrorAction SilentlyContinue | ForEach-Object {
            $pidStr = Get-Content $_.FullName -ErrorAction SilentlyContinue
            if ($pidStr -match '^\d+$') { $pids += [int]$pidStr }
        }
    }
    return $pids
}

function Get-ProtectedPIDs {
    $protected = @()
    if ($ProtectPIDs -ne "") {
        $ProtectPIDs.Split(',') | ForEach-Object {
            $p = $_.Trim()
            if ($p -match '^\d+$') { $protected += [int]$p }
        }
    }
    # Always protect the parent PID (spiral.sh orchestrator)
    if ($ParentPID -gt 0) { $protected += $ParentPID }
    return $protected
}

function Stop-TargetedNodeProcess {
    $workerPIDs = Get-WorkerPIDs
    $protectedPIDs = Get-ProtectedPIDs

    if ($workerPIDs.Count -eq 0) {
        Write-Log "EMERGENCY: No worker PIDs found in '$WorkerPIDDir' — skipping kill to protect Claude Code"
        return
    }

    # Only kill processes that are known workers AND not protected
    $candidate = $null
    foreach ($wpid in $workerPIDs) {
        if ($wpid -in $protectedPIDs) { continue }
        try {
            $proc = Get-Process -Id $wpid -ErrorAction SilentlyContinue
            if ($null -ne $proc) {
                if ($null -eq $candidate -or $proc.WorkingSet64 -gt $candidate.WorkingSet64) {
                    $candidate = $proc
                }
            }
        } catch { }
    }

    if ($null -ne $candidate) {
        $rssMB = [math]::Floor($candidate.WorkingSet64 / 1024 / 1024)
        Write-Log "EMERGENCY KILL (targeted): worker PID=$($candidate.Id) RSS=${rssMB}MB (level 4)"
        try {
            Stop-Process -Id $candidate.Id -Force -ErrorAction Stop
            Write-Log "KILLED: PID=$($candidate.Id) successfully terminated"
        } catch {
            Write-Log "KILL FAILED: PID=$($candidate.Id) - $($_.Exception.Message)"
        }
    } else {
        Write-Log "EMERGENCY: No killable worker processes found — memory critical but cannot safely kill"
    }
}

# ── Start ─────────────────────────────────────────────────────────────────────

if ($GraduatedMode) {
    $preemptiveMsg = if ($PreemptivePressureMB -gt 0) { ", PreemptivePressureMB=$PreemptivePressureMB" } else { "" }
    Write-Log "Watchdog started (GRADUATED): ScratchDir=$ScratchDir, ThresholdPct=$ThresholdPct, Hysteresis=$Hysteresis, IntervalSec=$IntervalSec, ParentPID=$ParentPID$preemptiveMsg"
} else {
    Write-Log "Watchdog started (KILL-ONLY): ThresholdMB=$ThresholdMB, ParentPID=$ParentPID, IntervalSec=$IntervalSec"
}

while ($true) {
    # Self-terminate if parent process is gone
    if ($ParentPID -gt 0) {
        try {
            $parent = Get-Process -Id $ParentPID -ErrorAction Stop
        } catch {
            Write-Log "Parent PID $ParentPID exited - watchdog shutting down"
            # Clean up signal files on exit
            if ($GraduatedMode) {
                Remove-Item -Path $PressureFile -Force -ErrorAction SilentlyContinue
                Remove-Item -Path $LowPowerFlag -Force -ErrorAction SilentlyContinue
            }
            break
        }
    }

    if ($GraduatedMode) {
        # ── Graduated pressure mode ──────────────────────────────────────────
        $mem = Get-SystemMemoryInfo
        $nodeProcs = Get-NodeProcessCount
        $rawLevel = Get-PressureLevel -FreePct $mem.FreePct

        # Hysteresis: only report a drop after N consecutive lower readings
        if ($rawLevel -lt $ReportedLevel) {
            $ConsecutiveLowerCount++
            if ($ConsecutiveLowerCount -ge $Hysteresis) {
                $ReportedLevel = $rawLevel
                $ConsecutiveLowerCount = 0
                Write-Log "Pressure DROP: level $ReportedLevel (free: $($mem.FreePct)% = $($mem.FreeMB)MB, nodes: $nodeProcs)"
            }
            # else: hold at current reported level until hysteresis threshold met
        } elseif ($rawLevel -gt $ReportedLevel) {
            # Immediate escalation - no hysteresis for increases
            $ReportedLevel = $rawLevel
            $ConsecutiveLowerCount = 0
            Write-Log "Pressure RISE: level $ReportedLevel (free: $($mem.FreePct)% = $($mem.FreeMB)MB, nodes: $nodeProcs)"
        } else {
            # Same level - reset counter
            $ConsecutiveLowerCount = 0
        }

        # Predictive preemptive pressure: if free RAM drops below PreemptivePressureMB
        # and we're currently at level 0, pre-escalate to level 1 proactively (Idea 7).
        # This gives the adaptive pause/resume system time to throttle before RAM is critical.
        $EffectiveLevel = $ReportedLevel
        if ($PreemptivePressureMB -gt 0 -and $EffectiveLevel -eq 0 -and $mem.FreeMB -lt $PreemptivePressureMB) {
            $EffectiveLevel = 1
            Write-Log "Predictive preemptive pressure: free=${mem.FreeMB}MB < threshold=${PreemptivePressureMB}MB — reporting level 1 (was 0)"
        }

        $recommendations = Get-Recommendations -Level $EffectiveLevel -FreeMB $mem.FreeMB -NodeProcs $nodeProcs
        Write-PressureFile -Level $EffectiveLevel -FreeMB $mem.FreeMB -NodeProcs $nodeProcs -Recommendations $recommendations

        # Manage low-power flag file
        if ($ReportedLevel -ge 2) {
            if (-not (Test-Path $LowPowerFlag)) {
                Set-Content -Path $LowPowerFlag -Value "1" -ErrorAction SilentlyContinue
                Write-Log "Low power mode ACTIVATED (level $ReportedLevel)"
            }
        } else {
            if (Test-Path $LowPowerFlag) {
                Remove-Item -Path $LowPowerFlag -Force -ErrorAction SilentlyContinue
                Write-Log "Low power mode DEACTIVATED (level $ReportedLevel)"
            }
        }

        # Level 4: emergency kill (targeted worker process only, never Claude Code)
        if ($ReportedLevel -ge 4) {
            Stop-TargetedNodeProcess
        }

    } else {
        # ── Kill-only mode (backwards compatible) ────────────────────────────
        try {
            $nodeProcs = Get-Process -Name "node" -ErrorAction SilentlyContinue
            foreach ($proc in $nodeProcs) {
                $rssMB = [math]::Floor($proc.WorkingSet64 / 1024 / 1024)
                if ($proc.WorkingSet64 -gt $ThresholdBytes) {
                    Write-Log "KILL: node.exe PID=$($proc.Id) RSS=${rssMB}MB > threshold ${ThresholdMB}MB"
                    try {
                        Stop-Process -Id $proc.Id -Force -ErrorAction Stop
                        Write-Log "KILLED: PID=$($proc.Id) successfully terminated"
                    } catch {
                        Write-Log "KILL FAILED: PID=$($proc.Id) - $($_.Exception.Message)"
                    }
                }
            }
        } catch {
            # Get-Process can fail transiently - ignore and retry
        }
    }

    Start-Sleep -Seconds $IntervalSec
}

Write-Log "Watchdog exited"
