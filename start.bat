@echo off
chcp 65001 >nul 2>&1
title MSMP Website
cd /d %~dp0

:: 使用 managed Python + venv 依赖
set PYTHONPATH=%~dp0venv\Lib\site-packages
set PYTHON_CMD=C:\Users\mckin\.workbuddy\binaries\python\versions\3.13.12\python.exe

echo  Starting MSMP Website...
echo  http://localhost:5000
echo.

%PYTHON_CMD% server.py
pause
