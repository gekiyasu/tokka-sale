@echo off
title [ACTIVE] Amazon Sale Bot
cd /d "%~dp0"
echo ======================================================
echo  Amazon Sale Bot is RUNNING...
echo  Keep this window open to maintain 24/7 auto-posting.
echo ======================================================
echo.
py -3 -u main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Process exited with code %ERRORLEVEL%
    pause
)
