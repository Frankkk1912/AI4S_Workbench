param(
    [Parameter(Mandatory = $true)]
    [string]$ReportPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$PluginRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PluginRoot "..\.."))
$SourceRoot = Join-Path $PluginRoot "source"
$Checks = New-Object System.Collections.Generic.List[object]
$Artifacts = [ordered]@{}

function Add-Check {
    param([string]$Name, [string]$Status, [long]$DurationMs, [string]$Message)
    $Checks.Add([pscustomobject]@{
        name = $Name
        status = $Status
        duration_ms = $DurationMs
        message = $Message
    })
}

function Invoke-External {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$Command exited with code $LASTEXITCODE."
    }
}

function Invoke-InDirectory {
    param([string]$Directory, [scriptblock]$Action)
    $pushed = $false
    try {
        Push-Location -LiteralPath $Directory
        $pushed = $true
        & $Action | Out-Host
    }
    finally {
        if ($pushed) {
            Pop-Location
        }
    }
}

function Invoke-Check {
    param([string]$Name, [scriptblock]$Action)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $Action | Out-Host
        $watch.Stop()
        Add-Check -Name $Name -Status "passed" -DurationMs $watch.ElapsedMilliseconds -Message "Completed successfully."
    }
    catch {
        $watch.Stop()
        Add-Check -Name $Name -Status "failed" -DurationMs $watch.ElapsedMilliseconds -Message $_.Exception.Message
        Write-Warning "$Name failed: $($_.Exception.Message)"
    }
}

function Get-ToolVersion {
    param([string]$Command, [string[]]$Arguments)
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        return "unavailable"
    }
    try {
        return ((& $Command @Arguments 2>$null) | Select-Object -First 1).ToString().Trim()
    }
    catch {
        return "unknown"
    }
}

$target = [System.IO.Path]::GetFullPath($ReportPath)
$bootstrapReport = Join-Path ([System.IO.Path]::GetTempPath()) "ai4s-literature-bootstrap-report.json"

Invoke-Check -Name "codex-plugin-visible" -Action {
    $pluginList = & codex plugin list 2>&1
    $pluginList | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "codex plugin list exited with code $LASTEXITCODE."
    }
    if (($pluginList -join "`n") -notmatch "literature-workbench") {
        throw "literature-workbench is not visible in the configured Codex marketplaces."
    }
}

Invoke-Check -Name "bootstrap-all-runtimes" -Action {
    & (Join-Path $PSScriptRoot "bootstrap-runtime.ps1") -RequireOptional -ReportPath $bootstrapReport
}

Invoke-Check -Name "zotero-runtime-tests" -Action {
    Invoke-InDirectory -Directory (Join-Path $SourceRoot "literature-zotero-mcp") -Action {
        Invoke-External -Command "npm" -Arguments @("ci")
        Invoke-External -Command "npm" -Arguments @("test")
        Invoke-External -Command "npm" -Arguments @("run", "typecheck")
    }
}

Invoke-Check -Name "fulltext-runtime-tests" -Action {
    Invoke-InDirectory -Directory (Join-Path $SourceRoot "literature-fulltext-mcp") -Action {
        Invoke-External -Command "npm" -Arguments @("ci")
        Invoke-External -Command "npm" -Arguments @("test")
        Invoke-External -Command "npm" -Arguments @("run", "typecheck")
    }
}

Invoke-Check -Name "python-skill-tests" -Action {
    Invoke-InDirectory -Directory $RepoRoot -Action {
        Invoke-External -Command "uv" -Arguments @("run", "-m", "unittest", "discover", "-s", "skills/literature-research/tests", "-p", "test_*.py")
        Invoke-External -Command "uv" -Arguments @("run", "-m", "unittest", "discover", "-s", "skills/literature-manager/tests", "-p", "test_*.py")
    }
}

Invoke-Check -Name "bundle-drift-check" -Action {
    Invoke-InDirectory -Directory $RepoRoot -Action {
        Invoke-External -Command "node" -Arguments @("plugins/literature-workbench/scripts/assemble-plugin.mjs", "check")
    }
}

Invoke-Check -Name "literature-metrics-xpi" -Action {
    $metricsRoot = Join-Path $SourceRoot "literature-metrics"
    Invoke-InDirectory -Directory $metricsRoot -Action {
        Invoke-External -Command "npm" -Arguments @("ci")
        Invoke-External -Command "npm" -Arguments @("test")
        Invoke-External -Command "npm" -Arguments @("run", "check")
        Invoke-External -Command "npm" -Arguments @("run", "package")
    }
    $xpi = Get-ChildItem -LiteralPath (Join-Path $metricsRoot "dist") -Filter "literature-metrics-*.xpi" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $xpi) {
        throw "No literature-metrics XPI was produced."
    }
    $script:Artifacts["xpi"] = $xpi.FullName
}

$Artifacts.bootstrap_report = $bootstrapReport
$failedChecks = @($Checks | Where-Object { $_.status -eq "failed" })
$overall = if ($failedChecks.Count -eq 0) { "passed" } else { "failed" }
$parent = Split-Path -Parent $target
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

$report = [ordered]@{
    schema_version = 1
    generated_at = [DateTime]::UtcNow.ToString("o")
    host = [ordered]@{
        os = [Environment]::OSVersion.VersionString
        powershell = $PSVersionTable.PSVersion.ToString()
        node = Get-ToolVersion -Command "node" -Arguments @("--version")
        npm = Get-ToolVersion -Command "npm" -Arguments @("--version")
        uv = Get-ToolVersion -Command "uv" -Arguments @("--version")
        codex = Get-ToolVersion -Command "codex" -Arguments @("--version")
    }
    checks = $Checks.ToArray()
    artifacts = $Artifacts
    overall_status = $overall
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $target -Encoding UTF8
Write-Output "Windows acceptance report written to: $target"

if ($overall -ne "passed") {
    throw "Windows acceptance failed. Review the report at $target."
}
