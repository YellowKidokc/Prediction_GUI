@echo off
python "%~dp0run.py" -m nlp.cli %*
exit /b %errorlevel%
