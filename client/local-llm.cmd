@echo off
REM local-llm add 192.168.1.189 / remove 192.168.1.189 / list / unregister. Double-clicked, it lists.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local-llm.ps1" %*
set code=%errorlevel%
if "%~1"=="" pause
exit /b %code%
