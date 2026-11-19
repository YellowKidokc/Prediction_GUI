@echo off
python "%~dp0setup_env.py" %*
exit /b %errorlevel%
