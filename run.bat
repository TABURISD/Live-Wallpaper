@echo off
cd /d "%~dp0"
"%DAIMON_USER_PYTHON%" -m app 2>nul || python -m app
