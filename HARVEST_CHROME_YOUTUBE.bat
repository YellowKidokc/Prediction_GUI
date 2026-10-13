@echo off
cd /d "%~dp0"
python -m harness.adapters.chrome_history
pause
