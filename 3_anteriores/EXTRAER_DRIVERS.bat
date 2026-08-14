@echo off
chcp 65001 >nul
title Extractor de Drivers - Mercado Libre
cd /d "%~dp0"
python extraer_drivers.py
pause
