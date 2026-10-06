@echo off
cd /d "%~dp0"
py -3 -m py_compile main.py
if errorlevel 1 goto :fail
echo Python syntax: OK
start "MAYA_AGENT_HUB TEST" /B py -3 main.py
ping 127.0.0.1 -n 3 >nul
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8065/api/status).StatusCode } catch { Write-Error $_; exit 1 }"
if errorlevel 1 goto :fail
echo API: OK
echo Open http://localhost:8065
exit /b 0
:fail
echo TEST FAILED
exit /b 1
