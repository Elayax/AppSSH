#!/bin/bash
# RUT956 CONFIGURATOR - Script de instalación rápida

echo "🔧 RUT956 CONFIGURATOR v1.0"
echo "=============================="
echo ""

# Verificar si Python está instalado
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 no está instalado"
    echo "Descarga Python desde: https://www.python.org/downloads/"
    exit 1
fi

echo "✓ Python encontrado"
python3 --version
echo ""

# Crear entorno virtual (opcional pero recomendado)
echo "Creando entorno virtual..."
python3 -m venv venv

# Activar entorno virtual
echo "Activando entorno virtual..."
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null

# Instalar dependencias
echo ""
echo "Instalando dependencias..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt

echo ""
echo "✓ Instalación completada"
echo ""
echo "Para ejecutar la herramienta:"
echo ""
echo "  python main.py"
echo ""
echo "O directamente sin activar venv:"
echo ""
echo "  python3 main.py"
echo ""
