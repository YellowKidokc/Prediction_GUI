@echo off
python "%~dp0run.py" -m harness.adapters.chrome_history %*
exit /b %errorlevel%
