@echo off
title Install DJI2AMC Dependencies
echo.
echo Installing required Python packages...
echo.
py -m pip install --upgrade pip
py -m pip install -r "%~dp0requirements.txt"
echo.
echo Done.
pause
