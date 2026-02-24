@echo off
REM RUT956 CONFIGURATOR - Script de instalación para Windows

echo.
echo 0x0A RUT956 CONFIGURATOR v1.0
echo ==============================
echo.

REM Verificar si Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python no está instalado
    echo.
    echo Descarga Python desde: https://www.python.org/downloads/
    echo Marca "Add Python to PATH" durante la instalación
    pause
    exit /b 1
)

echo [OK] Python encontrado
python --version
echo.

REM Crear entorno virtual
echo Creando entorno virtual...
python -m venv venv

REM Activar entorno virtual
echo Activando entorno virtual...
call venv\Scripts\activate.bat

REM Instalar dependencias
echo.
echo Instalando dependencias...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt

echo.
echo [OK] Instalación completada
echo.
echo Para ejecutar la herramienta:
echo.
echo   python main.py
echo.
pause
