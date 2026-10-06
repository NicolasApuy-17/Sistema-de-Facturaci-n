@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta Instalar.cmd.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\configure.py
if errorlevel 1 pause
