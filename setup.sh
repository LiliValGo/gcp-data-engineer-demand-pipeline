#!/bin/bash

echo "╔════════════════════════════════════════════════════════╗"
echo "║   Job Market Role Explorer - Setup Script              ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Check Python
python_cmd=$(command -v python3 || command -v python)
if [ -z "$python_cmd" ]; then
    echo "❌ Python no encontrado. Instala Python 3.8+ primero."
    exit 1
fi

echo "✓ Python encontrado: $python_cmd"

# Check/create venv
if [ ! -d "venv" ]; then
    echo "📦 Creando virtual environment..."
    $python_cmd -m venv venv
fi

# Activate venv
echo "🔧 Activando virtual environment..."
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null

# Upgrade pip
echo "⬆️  Actualizando pip..."
pip install --upgrade pip -q

# Install requirements
echo "📦 Instalando dependencias desde requirements.txt..."
pip install -r requirements.txt -q

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║   ✅ Setup Completado                                  ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Próximos pasos:"
echo "  1. Activa el venv: source venv/bin/activate"
echo "  2. Corre el scraper: python main_scraper.py"
echo "  3. O corre la web app: python run_web.py"
echo ""
