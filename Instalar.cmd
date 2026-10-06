@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Preparando Control Empresa...
where py >nul 2>nul
if errorlevel 1 (
  echo Instala Python 3.12 de 64 bits desde https://www.python.org/downloads/windows/
  echo Incluye el lanzador py durante la instalacion y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)
py -3.12 -m venv .venv
if errorlevel 1 (
  echo Se necesita Python 3.12 con pip. Revisa la instalacion.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo No se pudieron instalar las dependencias. Revisa la conexion a internet.
  pause
  exit /b 1
)
echo Listo. Abre Configurar.cmd.
pause
