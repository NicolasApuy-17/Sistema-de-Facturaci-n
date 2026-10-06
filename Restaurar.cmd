@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\restore.py
if errorlevel 1 pause
