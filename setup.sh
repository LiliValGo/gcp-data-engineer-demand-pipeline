#!/bin/bash

echo "╔════════════════════════════════════════════════════════╗"
echo "║   Job Market Role Explorer - Setup Script              ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Check Python
python_cmd=$(command -v python3 || command -v python)
if [ -z "$python_cmd" ]; then
    echo "Python not found. Please install Python 3.8+ first."
    exit 1
fi

echo "Python found: $python_cmd"

# Check/create venv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $python_cmd -m venv venv
fi

# Activate venv
echo "Activating virtual environment..."
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip -q

# Install requirements
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt -q

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║      Setup Completed                                   ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Activate the venv: source venv/bin/activate"
echo "  2. Run the scraper: python main_scraper.py"
echo "  3. Or run the MCP server: python run_mcp.py"
echo ""
