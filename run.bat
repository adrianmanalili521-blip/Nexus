@echo off
cd /d "%~dp0"
py -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  echo Installing required package PySide6...
  py -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Installation failed. Check Python and internet connection.
    pause
    exit /b 1
  )
)
py main.py
if errorlevel 1 pause
