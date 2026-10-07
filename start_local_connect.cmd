@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || goto :directory_error

set "LC_PYTHON_CMD="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 set "LC_PYTHON_CMD=py -3"
if not defined LC_PYTHON_CMD (
  python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
  if not errorlevel 1 set "LC_PYTHON_CMD=python"
)
if not defined LC_PYTHON_CMD (
  echo Python 3.10 or newer is required. Install Python with pip enabled.
  goto :failed
)

%LC_PYTHON_CMD% run_local_connect.py %*
if errorlevel 1 goto :failed
popd
exit /b 0

:failed
echo.
echo Local Connect could not start. Review the error above.
pause
popd
exit /b 1

:directory_error
echo Cannot open the Local Connect folder.
pause
exit /b 1
