@echo off
REM RUT956 CONFIGURATOR - Script de arranque

if not exist venv (
    echo [X] Entorno virtual no encontrado.
    echo     Por favor ejecuta primero: install.bat
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python main.py
