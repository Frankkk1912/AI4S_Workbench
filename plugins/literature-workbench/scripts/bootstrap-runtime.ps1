param(
    [switch]$RequireOptional,
    [string]$ReportPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$PluginRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $PluginRoot "runtime"
$FulltextRuntimeDir = Join-Path $PluginRoot "fulltext-runtime"
$Checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [string]$Name,
        [string]$Status,
        [long]$DurationMs,
        [string]$Message
    )

    $Checks.Add([pscustomobject]@{
        name = $Name
        status = $Status
        duration_ms = $DurationMs
        message = $Message
    })
}

function Invoke-External {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    & $Command @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$Command exited with code $LASTEXITCODE."
    }
}

function Invoke-RuntimeBootstrap {
    param(
        [string]$Name,
        [string]$Directory,
        [string]$Verifier
    )

    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $pushed = $false
    try {
        if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
            throw "Runtime directory does not exist: $Directory"
        }
        Push-Location -LiteralPath $Directory
        $pushed = $true
        Invoke-External -Command "npm" -Arguments @("ci")
        Invoke-External -Command "npm" -Arguments @("run", "build")
        Invoke-External -Command $script:NodeCommand -Arguments @($Verifier)
        $watch.Stop()
        Add-Check -Name $Name -Status "passed" -DurationMs $watch.ElapsedMilliseconds -Message "Runtime built and verified over stdio."
        return $true
    }
    catch {
        $watch.Stop()
        Add-Check -Name $Name -Status "failed" -DurationMs $watch.ElapsedMilliseconds -Message $_.Exception.Message
        return $false
    }
    finally {
        if ($pushed) {
            Pop-Location
        }
    }
}

function Write-BootstrapReport {
    param([string]$OverallStatus)

    if ([string]::IsNullOrWhiteSpace($ReportPath)) {
        return
    }

    $target = [System.IO.Path]::GetFullPath($ReportPath)
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
            node = (& $script:NodeCommand --version)
            npm = (& npm --version)
        }
        checks = $Checks.ToArray()
        artifacts = [ordered]@{
            plugin_root = $PluginRoot
        }
        overall_status = $OverallStatus
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $target -Encoding UTF8
    Write-Output "Bootstrap report written to: $target"
}

$nodeInfo = Get-Command node -ErrorAction SilentlyContinue
$npmInfo = Get-Command npm -ErrorAction SilentlyContinue
if (-not $nodeInfo -or -not $npmInfo) {
    throw "Node.js and npm are required. Install Node.js 20.19 or newer."
}
$NodeCommand = $nodeInfo.Source

$Version = (& $NodeCommand -p "process.versions.node").Trim().Split(".")
if ([int]$Version[0] -lt 20 -or ([int]$Version[0] -eq 20 -and [int]$Version[1] -lt 19)) {
    throw "Node.js $($Version -join '.') is unsupported; require Node.js 20.19 or newer."
}

$zoteroReady = Invoke-RuntimeBootstrap `
    -Name "zotero-runtime" `
    -Directory $RuntimeDir `
    -Verifier (Join-Path $PluginRoot "scripts\verify-runtime.mjs")

$fulltextReady = Invoke-RuntimeBootstrap `
    -Name "fulltext-runtime" `
    -Directory $FulltextRuntimeDir `
    -Verifier (Join-Path $PluginRoot "scripts\verify-fulltext-runtime.mjs")

if (-not $fulltextReady) {
    Write-Warning "The optional literature Fulltext MCP was not installed. Zotero MCP and literature skills remain available."
}

$failed = -not $zoteroReady -or ($RequireOptional -and -not $fulltextReady)
$overall = if ($failed) { "failed" } elseif (-not $fulltextReady) { "partial" } else { "passed" }
Write-BootstrapReport -OverallStatus $overall

if (-not $zoteroReady) {
    throw "The required Zotero MCP runtime failed to bootstrap."
}
if ($RequireOptional -and -not $fulltextReady) {
    throw "The optional Fulltext MCP runtime failed and -RequireOptional was specified."
}

Write-Output "Literature Workbench runtime bootstrap completed with status: $overall"
Write-Output ""
Write-Output "Optional API onboarding is available; basic literature features work without keys."
Write-Output "On the first workbench conversation, the Agent will explain Zotero Web API, PubMed, and EasyScholar setup."
Write-Output "Local masked wizard: node `"$PSScriptRoot\onboard.mjs`" setup --output onboarding-result.json"
