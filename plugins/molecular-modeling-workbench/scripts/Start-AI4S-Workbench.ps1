#Requires -Version 5.1
<#
.SYNOPSIS
Runs a non-destructive Windows 11 preflight for the AI4S Workbench.

.DESCRIPTION
This script only reads host and WSL state and writes JSON/Markdown diagnostics.
It never elevates, enables Windows features, installs software, restarts Windows,
or runs docking/MD commands. Review this local file before running it.

Each run creates a new output directory. An explicitly selected output path must
not already exist, including a symbolic link or reparse point.
#>
[CmdletBinding()]
param(
    [string]$Distribution = "Ubuntu-22.04",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$checks = [System.Collections.Generic.List[object]]::new()
$handoffs = [System.Collections.Generic.List[string]]::new()

function Add-Check {
    param(
        [string]$Id,
        [string]$Status,
        [string]$Summary,
        [string]$Evidence = ""
    )
    $checks.Add([ordered]@{
        id = $Id
        status = $Status
        summary = $Summary
        evidence = $Evidence
    })
}

function Invoke-ReadOnlyCommand {
    param([string]$Command, [string[]]$Arguments)
    try {
        $output = & $Command @Arguments 2>&1 | Out-String
        return [ordered]@{ exit_code = $LASTEXITCODE; output = $output.Trim() }
    }
    catch {
        return [ordered]@{ exit_code = 1; output = $_.Exception.Message }
    }
}

function Get-ReadableCommandEvidence {
    param(
        [string]$Text,
        [string]$Fallback
    )
    if ([string]::IsNullOrWhiteSpace($Text) -or $Text.Contains([char]0) -or $Text.Contains([char]0xFFFD)) {
        return $Fallback
    }
    foreach ($character in $Text.ToCharArray()) {
        if ([char]::IsControl($character) -and $character -notin @("`r", "`n", "`t")) {
            return $Fallback
        }
    }
    return $Text.Trim()
}

function Get-CleanWslLines {
    param([string]$Text)
    return @(($Text -replace [char]0, "") -split "`r?`n" | ForEach-Object {
        $_.Trim().TrimStart([char]0xFEFF)
    } | Where-Object { $_ })
}

function Get-ExactWslDistribution {
    param(
        [string]$QuietOutput,
        [string]$VerboseOutput,
        [string]$DistributionName
    )

    $quietNames = @(Get-CleanWslLines $QuietOutput)
    if (-not ($quietNames | Where-Object { $_ -ceq $DistributionName })) {
        return [ordered]@{ installed = $false; version = 0; evidence = "" }
    }

    foreach ($line in @(Get-CleanWslLines $VerboseOutput)) {
        $candidate = $line -replace '^\s*\*?\s*', ''
        if ($candidate -match '^(?<name>\S+)\s+.+?\s+(?<version>[12])\s*$' -and $Matches.name -ceq $DistributionName) {
            return [ordered]@{
                installed = $true
                version = [int]$Matches.version
                evidence = $line
            }
        }
    }
    return [ordered]@{ installed = $true; version = 0; evidence = "Exact distribution found, but its WSL version could not be parsed." }
}

function Write-Utf8CreateNew {
    param([string]$Path, [string]$Content)
    $encoding = [System.Text.UTF8Encoding]::new($false)
    $stream = [System.IO.FileStream]::new(
        $Path,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        $writer = [System.IO.StreamWriter]::new($stream, $encoding)
        try { $writer.Write($Content) } finally { $writer.Dispose() }
    }
    finally {
        if ($stream) { $stream.Dispose() }
    }
}

if (-not $OutputDirectory) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $OutputDirectory = Join-Path $PWD "ai4s-onboarding-$stamp-$PID"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$existingOutput = Get-Item -LiteralPath $OutputDirectory -Force -ErrorAction SilentlyContinue
if ($existingOutput -or [System.IO.File]::Exists($OutputDirectory) -or [System.IO.Directory]::Exists($OutputDirectory)) {
    throw "Refusing to overwrite existing onboarding output: $OutputDirectory. Choose a new -OutputDirectory."
}
New-Item -ItemType Directory -Path $OutputDirectory -ErrorAction Stop | Out-Null
$outputItem = Get-Item -LiteralPath $OutputDirectory -Force
if (($outputItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Refusing an onboarding output directory that is a reparse point: $OutputDirectory"
}

$canProbeHost = $true
if ($env:OS -ne "Windows_NT") {
    Add-Check "windows-host" "fail" "Run this preflight from Windows PowerShell, not inside WSL or native Linux." "$($env:OS)"
    $canProbeHost = $false
}
if ($Distribution -cne "Ubuntu-22.04") {
    Add-Check "requested-distribution" "fail" "v0.2.0 supports only the explicitly selected Ubuntu-22.04 distribution." $Distribution
    $canProbeHost = $false
}

$distributionInstalled = $false
$distributionVersion2 = $false
if ($canProbeHost) {
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $build = [int]$os.BuildNumber
        if ($build -ge 22000) {
            Add-Check "windows-11" "pass" "Windows 11 detected." "$($os.Caption), build $build"
        }
        else {
            Add-Check "windows-11" "fail" "Windows 11 is required for the v0.2.0 supported route." "$($os.Caption), build $build"
        }
    }
    catch {
        Add-Check "windows-11" "unknown" "Windows version could not be read; review the error before continuing." $_.Exception.Message
    }

    $wslCommand = Get-Command "wsl.exe" -ErrorAction SilentlyContinue
    if (-not $wslCommand) {
        Add-Check "wsl" "action-needed" "WSL is not available. Installation requires an elevated user action and may require a reboot." "wsl.exe was not found"
        $handoffs.Add("Open an Administrator PowerShell yourself, review Microsoft's WSL instructions, then run: wsl --install -d Ubuntu-22.04")
    }
    else {
        $status = Invoke-ReadOnlyCommand $wslCommand.Source @("--status")
        if ($status.exit_code -eq 0) {
            Add-Check "wsl" "pass" "WSL is available." "wsl.exe --status exited with code 0."
        }
        else {
            $statusEvidence = Get-ReadableCommandEvidence $status.output "wsl.exe --status exited with code $($status.exit_code); no readable diagnostic text was captured."
            Add-Check "wsl" "action-needed" "WSL exists but its status check failed. This can indicate a pending reboot, disabled virtualization, or enterprise policy." $statusEvidence
            $handoffs.Add("Review Microsoft WSL troubleshooting. Do not bypass organizational policy or change BIOS settings through an Agent.")
        }

        $quietList = Invoke-ReadOnlyCommand $wslCommand.Source @("--list", "--quiet")
        $verboseList = Invoke-ReadOnlyCommand $wslCommand.Source @("--list", "--verbose")
        $distributionRecord = Get-ExactWslDistribution $quietList.output $verboseList.output $Distribution
        if ($quietList.exit_code -eq 0 -and $verboseList.exit_code -eq 0 -and $distributionRecord.installed) {
            $distributionInstalled = $true
            $distributionVersion2 = $distributionRecord.version -eq 2
            if ($distributionVersion2) {
                Add-Check "ubuntu-22.04-wsl2" "pass" "$Distribution is installed as WSL2." $distributionRecord.evidence
            }
            else {
                Add-Check "ubuntu-22.04-wsl2" "action-needed" "$Distribution is installed but is not confirmed as WSL2." $distributionRecord.evidence
                $handoffs.Add("Review the distribution and, after making a backup, explicitly convert it with: wsl --set-version Ubuntu-22.04 2")
            }
        }
        else {
            Add-Check "ubuntu-22.04-wsl2" "action-needed" "The exact $Distribution distribution is not installed." $quietList.output
            $handoffs.Add("Open an Administrator PowerShell yourself and, after review, run: wsl --install -d Ubuntu-22.04")
        }
    }

    $nvidia = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
    if ($nvidia) {
        $gpu = Invoke-ReadOnlyCommand $nvidia.Source @("--query-gpu=name,driver_version", "--format=csv,noheader")
        if ($gpu.exit_code -eq 0) {
            Add-Check "nvidia-host-driver" "pass" "The Windows NVIDIA driver responds." $gpu.output
        }
        else {
            Add-Check "nvidia-host-driver" "action-needed" "The NVIDIA diagnostic failed; GPU readiness must be fixed before release-equivalent MD." $gpu.output
        }
    }
    else {
        Add-Check "nvidia-host-driver" "action-needed" "No Windows NVIDIA diagnostic was found. GPU MD will not be ready until a compatible host driver is installed manually." "nvidia-smi.exe was not found"
        $handoffs.Add("Install or update only the official Windows NVIDIA driver. Do not install a Linux display driver inside WSL.")
    }

    $dockerDesktopPaths = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Docker\Docker Desktop.exe")
    )
    $dockerDesktop = $dockerDesktopPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($dockerDesktop) {
        Add-Check "docker-desktop" "detected" "Docker Desktop is installed; its Ubuntu-22.04 WSL integration still must be enabled and verified inside WSL." $dockerDesktop
    }
    else {
        Add-Check "docker-desktop" "action-needed" "Docker Desktop was not detected. Choose and install a supported container runtime manually after reviewing licensing and policy." "No standard installation path found"
        $handoffs.Add("Review Docker Desktop's WSL2 backend documentation or an administrator-approved WSL-native Docker alternative; this script will not install either.")
    }
}

$requiredIds = @("windows-host", "requested-distribution", "windows-11", "wsl", "ubuntu-22.04-wsl2")
$failedRequired = @($checks | Where-Object { $requiredIds -contains $_.id -and $_.status -ne "pass" })
$readyForWslSetup = $canProbeHost -and $failedRequired.Count -eq 0 -and $distributionInstalled -and $distributionVersion2
$report = [ordered]@{
    schema_version = "1.0"
    artifact_type = "windows_wsl_preflight"
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    supported_host = "Windows 11"
    requested_distribution = $Distribution
    ready_for_wsl_setup = $readyForWslSetup
    checks = $checks
    manual_handoffs = $handoffs
    boundaries = @(
        "This preflight does not elevate, reboot, enable Windows features, install software, or run scientific commands.",
        "Docking and MD run only from WSL-native Codex CLI or Claude Code in the Linux home filesystem.",
        "Docker, GPU drivers, Agent authentication, and proprietary tools remain explicit user actions."
    )
}

$jsonPath = Join-Path $OutputDirectory "onboarding-preflight.json"
$markdownPath = Join-Path $OutputDirectory "onboarding-preflight.md"
Write-Utf8CreateNew $jsonPath (($report | ConvertTo-Json -Depth 8) + "`n")

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# AI4S Windows to WSL preflight")
$lines.Add("")
$lines.Add("Ready for WSL setup: **$readyForWslSetup**")
$lines.Add("")
$lines.Add("## Checks")
foreach ($check in $checks) {
    $lines.Add("- **$($check.status)** — $($check.summary)")
    if ($check.evidence) { $lines.Add("  - Evidence: ``$($check.evidence -replace "`r?`n", "; ")``") }
}
$lines.Add("")
$lines.Add("## Manual handoffs")
if ($handoffs.Count -eq 0) { $lines.Add("- None for the host preflight.") }
foreach ($handoff in $handoffs) { $lines.Add("- $handoff") }
$lines.Add("")
$lines.Add("No Windows host configuration was changed. This run wrote only the two diagnostic files in this new output directory.")
$lines.Add("")
$lines.Add("Next: open $Distribution, clone the public repository under your Linux home directory, and run ``bash scripts/setup-wsl-workbench.sh --agent codex`` or ``--agent claude`` from the plugin directory.")
Write-Utf8CreateNew $markdownPath (($lines -join "`r`n") + "`r`n")

Write-Host "Preflight written to: $jsonPath"
Write-Host "Beginner checklist written to: $markdownPath"
if (-not $readyForWslSetup) {
    Write-Warning "Host setup is not ready. Review the diagnostic files and manual handoffs. No Windows host configuration was changed."
    exit 2
}
Write-Host "Host preflight passed. Continue inside $Distribution; do not run docking or MD from a Windows desktop Agent."
