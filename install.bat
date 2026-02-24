@echo off
REM RUT956 CONFIGURATOR - Script de instalación para Windows
setlocal enabledelayedexpansion

echo.
echo  ==========================================
echo    RUT956 CONFIGURATOR v1.0 - Instalador
echo  ==========================================
echo.

REM -----------------------------------------------
REM Buscar Python usando el launcher "py" (recomendado en Windows)
REM -----------------------------------------------
set PYTHON_CMD=

py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    echo [OK] Python encontrado via launcher "py"
    py --version
    goto :FOUND_PYTHON
)

REM Intentar con ruta directa donde se instaló Python 3.14
set PYTHON_PATH=C:\Users\smartinez\AppData\Local\Python\pythoncore-3.14-64\python.exe
if exist "%PYTHON_PATH%" (
    set PYTHON_CMD="%PYTHON_PATH%"
    echo [OK] Python encontrado en ruta directa
    %PYTHON_CMD% --version
    goto :FOUND_PYTHON
)

REM Último intento con python
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    echo [OK] Python encontrado via "python"
    python --version
    goto :FOUND_PYTHON
)

REM Si no encontró Python en ningún lado
echo [X] No se pudo encontrar Python instalado.
echo.
echo Soluciones:
echo  1. Descarga Python desde: https://www.python.org/downloads/
echo  2. Durante la instalacion, marca "Add Python to PATH"
echo  3. O usa el Python Launcher: https://www.python.org/downloads/
echo.
pause
exit /b 1

:FOUND_PYTHON
echo.

REM -----------------------------------------------
REM Crear entorno virtual
REM -----------------------------------------------
echo [>>] Creando entorno virtual en .\venv ...
if exist venv (
    echo [INFO] El entorno virtual ya existe, se recreara...
    rmdir /s /q venv
)

%PYTHON_CMD% -m venv venv
if %errorlevel% neq 0 (
    echo [X] Error al crear el entorno virtual
    pause
    exit /b 1
)
echo [OK] Entorno virtual creado correctamente
echo.

REM -----------------------------------------------
REM Activar entorno virtual
REM -----------------------------------------------
echo [>>] Activando entorno virtual...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [X] Error al activar el entorno virtual
    pause
    exit /b 1
)
echo [OK] Entorno virtual activado
echo.

REM -----------------------------------------------
REM Actualizar pip
REM -----------------------------------------------
echo [>>] Actualizando pip...
python -m pip install --upgrade pip --quiet
echo.

REM -----------------------------------------------
REM Instalar dependencias
REM -----------------------------------------------
echo [>>] Instalando dependencias desde requirements.txt...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [X] Error al instalar dependencias
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo  [OK] Instalacion completada exitosamente!
echo  ==========================================
echo.
echo  Para ejecutar la aplicacion:
echo.
echo    1. Doble clic en "run.bat"
echo    O manualmente:
echo      venv\Scripts\activate
echo      python main.py
echo.
pause
