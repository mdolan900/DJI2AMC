@echo off
title DJI2AMC
cd /d "%~dp0"
py DJI_to_Astro_AMC.py
if errorlevel 1 (
    echo.
    echo DJI2AMC exited with an error.
    pause
)
