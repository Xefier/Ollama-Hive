# Manages which rigs Claude Code can delegate to on this PC, for the current Windows user.
#
#   local-llm add 192.168.1.189            (port 11434 unless given: 192.168.1.189:11500)
#   local-llm remove 192.168.1.189
#   local-llm list                          (and whether each rig answers now)
#   local-llm unregister                    (removes every rig and the MCP server itself)
#
# The rig list lives only in the server's Claude Code registration (its OLLAMA_URLS), which each command rewrites.
# Keep this file ASCII: Windows PowerShell 5.1 reads a script without a BOM in the ANSI code page.

param(
    [Parameter(Position = 0)][ValidateSet('add', 'remove', 'list', 'unregister')][string]$Action = 'list',
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rigs
)

# Not Stop: in PowerShell 5.1 a native command's stderr then becomes a terminating error
$ErrorActionPreference = 'Continue'
$name = 'local-llm'
$defaultPort = 11434
$server = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'local_llm_mcp.py'

function Fail([string]$message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

function Find-Claude {
    $command = Get-Command claude -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $local = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
    if (Test-Path $local) { return $local }
    Fail 'Claude Code (claude) was not found on this PC.'
}

# The py launcher first: on many PCs "python" is the Microsoft Store stub, which opens the Store instead of running
function Find-Python {
    foreach ($candidate in @(@('py', '-3'), @('python'))) {
        $command = Get-Command $candidate[0] -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $arguments = @($candidate | Select-Object -Skip 1)
        $path = & $command.Source @arguments -c 'import sys; print(sys.executable) if sys.version_info >= (3, 8) else None' 2>$null
        if ($path -and (Test-Path $path.Trim())) { return $path.Trim() }
    }
    Fail 'Python 3.8 or newer was not found. Install it from python.org, then run this again.'
}

# 192.168.1.189, 192.168.1.189:11500 or http://192.168.1.189:11500, as http://host:port
function Normalize([string]$rig) {
    $rig = $rig.Trim().TrimEnd('/') -replace '^https?://', ''
    if ($rig -notmatch '^([A-Za-z0-9.-]+)(:(\d{1,5}))?$') { Fail "Not an address or address:port: $rig" }
    $port = if ($Matches[3]) { $Matches[3] } else { $defaultPort }
    return "http://$($Matches[1]):$port"
}

function Get-Registered([string]$claude) {
    $text = & $claude mcp get $name 2>&1 | Out-String
    if ($text -notmatch 'Scope:\s*User') { return $null }
    if ($text -match 'OLLAMA_URLS=(\S*)') { return @($Matches[1] -split ',' | Where-Object { $_ }) }
    return @()
}

function Show-Rigs([string[]]$urls) {
    foreach ($url in $urls) {
        try {
            $ps = Invoke-RestMethod -Uri "$url/api/ps" -TimeoutSec 3
            $model = @($ps.models)[0]
            if ($model) { Write-Host "  $url  $($model.name) loaded" -ForegroundColor Green }
            else { Write-Host "  $url  reachable, no model loaded yet" }
        } catch {
            Write-Host "  $url  not answering now (fine if that rig is on another flight sheet)" -ForegroundColor Yellow
        }
    }
}

# Rewrites the registration with this list; an empty list removes it
function Save-Rigs([string]$claude, [string[]]$urls, $current) {
    if ($null -ne $current) {
        & $claude mcp remove $name -s user 2>&1 | Out-Null
    }
    if (-not $urls) {
        Write-Host "No rigs left: $name is unregistered for $env:USERNAME."
        return
    }
    $python = Find-Python
    $output = & $claude mcp add $name --scope user -e "OLLAMA_URLS=$($urls -join ',')" -- $python $server 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Fail "claude mcp add failed: $output" }
}

$claude = Find-Claude
$current = Get-Registered $claude
# Assigned inside @() so a single rig stays an array: otherwise += would join the next URL onto it as one string
$list = @($current | Where-Object { $_ })

switch ($Action) {
    'list' {
        if ($null -eq $current) { Write-Host "$name is not registered for $env:USERNAME."; exit 0 }
        Write-Host "$name rigs for $env:USERNAME, tried in this order:"
        Show-Rigs $list
    }
    'add' {
        if (-not $Rigs) { Fail 'Usage: local-llm add <address>[:port] ...' }
        foreach ($rig in $Rigs) {
            $url = Normalize $rig
            if ($list -contains $url) { Write-Host "$url is already registered." } else { $list += $url }
        }
        Save-Rigs $claude $list $current
        Write-Host "$name rigs for $env:USERNAME, tried in this order:"
        Show-Rigs $list
        if ($null -eq $current) { Write-Host 'New Claude Code sessions get local_llm_ask and local_llm_status; sessions already open do not.' }
    }
    'remove' {
        if (-not $Rigs) { Fail 'Usage: local-llm remove <address>[:port] ...' }
        if ($null -eq $current) { Write-Host "$name is not registered for $env:USERNAME."; exit 0 }
        foreach ($rig in $Rigs) {
            $url = Normalize $rig
            if ($list -contains $url) { $list = @($list | Where-Object { $_ -ne $url }) } else { Write-Host "$url was not registered." }
        }
        Save-Rigs $claude $list $current
        if ($list) { Write-Host "$name rigs for $env:USERNAME, tried in this order:"; Show-Rigs $list }
    }
    'unregister' {
        if ($null -eq $current) { Write-Host "$name was not registered for $env:USERNAME."; exit 0 }
        Save-Rigs $claude @() $current
    }
}
