@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag an engine folder onto this file, or run:  INTAKE.bat engines\my_engine
  pause
  exit /b
)
python intake\intake.py "%~1"
pause
