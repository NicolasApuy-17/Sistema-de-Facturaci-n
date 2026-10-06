@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta Instalar.cmd.
  pause
  exit /b 1
)
start "Control Empresa" ".venv\Scripts\pythonw.exe" "%~dp0tools\serve_local.py" --background
