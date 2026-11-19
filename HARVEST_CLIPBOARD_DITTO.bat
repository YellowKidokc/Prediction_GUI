@echo off
python "%~dp0run.py" -m harness.adapters.clipboard ditto %*
exit /b %errorlevel%
