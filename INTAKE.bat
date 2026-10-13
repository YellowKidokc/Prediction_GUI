@echo off
cd /d "%~dp0"
set PY=python
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python.exe
if "%~1"=="" (
  echo Drag an engine folder onto this file, or run:  INTAKE.bat engines\my_engine
  pause
  exit /b
)
%PY% intake\intake.py "%~1"
pause
