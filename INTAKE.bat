@echo off
python "%~dp0run.py" intake/intake.py %*
exit /b %errorlevel%
