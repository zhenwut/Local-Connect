@echo off
cd /d "%~dp0"
python server.py
if errorlevel 1 (
  echo.
  echo Local Connect could not start. Review the error above.
  pause
)
