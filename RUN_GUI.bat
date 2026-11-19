@echo off
python "%~dp0run.py" gui/app.py
exit /b %errorlevel%
