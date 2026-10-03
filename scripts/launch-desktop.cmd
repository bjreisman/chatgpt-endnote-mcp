@echo off
setlocal DisableDelayedExpansion
if defined CHATGPT_ENDNOTE_MCP_COMMAND (
    set "executable=%CHATGPT_ENDNOTE_MCP_COMMAND%"
    goto launch
)
for %%E in (chatgpt-endnote-mcp.exe) do set "executable=%%~$PATH:E"
if defined executable goto launch
if defined UV_TOOL_BIN_DIR if exist "%UV_TOOL_BIN_DIR%\chatgpt-endnote-mcp.exe" (
    set "executable=%UV_TOOL_BIN_DIR%\chatgpt-endnote-mcp.exe"
    goto launch
)
if defined XDG_BIN_HOME if exist "%XDG_BIN_HOME%\chatgpt-endnote-mcp.exe" (
    set "executable=%XDG_BIN_HOME%\chatgpt-endnote-mcp.exe"
    goto launch
)
if defined XDG_DATA_HOME if exist "%XDG_DATA_HOME%\..\bin\chatgpt-endnote-mcp.exe" (
    set "executable=%XDG_DATA_HOME%\..\bin\chatgpt-endnote-mcp.exe"
    goto launch
)
if exist "%USERPROFILE%\.local\bin\chatgpt-endnote-mcp.exe" (
    set "executable=%USERPROFILE%\.local\bin\chatgpt-endnote-mcp.exe"
    goto launch
)
>&2 echo EndNote runtime is not installed. Ask Codex: Set up my EndNote library.
exit /b 127
:launch
if not exist "%executable%" (
    >&2 echo The configured EndNote runtime executable is unavailable.
    exit /b 127
)
"%executable%" serve-desktop %*
exit /b %errorlevel%
