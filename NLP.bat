@echo off
cd /d "%~dp0"
set PY=python
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python.exe
rem DeepSeek: local Ollama by default. For the hosted API: set DEEPSEEK_BACKEND=api and DEEPSEEK_API_KEY=...
if "%DEEPSEEK_MODEL%"=="" set DEEPSEEK_MODEL=deepseek-r1:8b
%PY% -m nlp.cli %*
pause
