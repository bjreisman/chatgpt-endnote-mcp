# Explicit onboarding only; never invoked by the MCP launcher.
param(
    [switch]$Semantic,
    [switch]$Replace,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
if ($Help) {
    Write-Output 'Usage: powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/install-desktop.ps1 [-Semantic] [-Replace]'
    exit 0
}
try {
    if ($env:CHATGPT_ENDNOTE_MCP_UV) {
        $uvCommand = $env:CHATGPT_ENDNOTE_MCP_UV
        if (-not (Test-Path -LiteralPath $uvCommand -PathType Leaf)) {
            [Console]::Error.WriteLine('The configured uv executable is unavailable. Install uv or correct CHATGPT_ENDNOTE_MCP_UV.')
            exit 127
        }
    } else {
        $found = Get-Command uv.exe -CommandType Application -ErrorAction SilentlyContinue
        if ($found) { $uvCommand = $found.Source }
        else { $uvCommand = Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
        if (-not (Test-Path -LiteralPath $uvCommand -PathType Leaf)) {
            [Console]::Error.WriteLine('uv is required. Install uv, then ask Codex to set up your EndNote library again.')
            exit 127
        }
    }
    $pluginRoot = Split-Path -Parent $PSScriptRoot
    $package = $pluginRoot
    if ($Semantic) { $package += '[semantic]' }
    $installArguments = @('tool', 'install')
    if ($Replace) { $installArguments += '--force' }
    $installArguments += $package
    & $uvCommand @installArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $binDirectory = & $uvCommand tool dir --bin
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $executable = Join-Path ([string]$binDirectory).Trim() 'chatgpt-endnote-mcp.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Installation did not produce $executable"
    }
    & $executable --version
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Output "Runtime executable: $executable"
    Write-Output 'Next: configure your XML/PDF paths, index, and run doctor. Use the plugin MCP connection; no direct MCP registration is needed.'
    Write-Output 'Restart Codex after installing/updating the runtime. For a custom uv bin directory, make CHATGPT_ENDNOTE_MCP_COMMAND available to Codex.'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
