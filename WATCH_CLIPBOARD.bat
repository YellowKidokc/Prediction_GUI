@echo off
python "%~dp0run.py" -m harness.adapters.clipboard watch %*
exit /b %errorlevel%
