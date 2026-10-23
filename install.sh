#!/bin/bash
set -e
cd "$(dirname "$0")"
G="\033[0;32m"; R="\033[0;31m"; Y="\033[1;33m"; N="\033[0m"
echo ""; echo "============================================================"
echo " AlgoEdge - Linux/Mac Installer"; echo "============================================================"; echo ""
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v $cmd &>/dev/null; then
        VER=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        MAJ=$(echo $VER|cut -d. -f1); MIN=$(echo $VER|cut -d. -f2)
        if [ "$MAJ"="3" ] && [ "$MIN" -ge "10" ] && [ "$MIN" -le "12" ]; then PYTHON=$cmd; echo -e "  ${G}✔ Found $cmd ($VER)${N}"; break; fi
    fi
done
if [ -z "$PYTHON" ]; then
    echo -e "${R}ERROR: Python 3.10-3.12 not found.${N}"
    echo "Ubuntu: sudo apt install python3.12 python3.12-venv"; exit 1
fi
echo ""; echo "Creating venv..."; rm -rf venv; $PYTHON -m venv venv; echo -e "  ${G}✔ Done${N}"
echo ""; echo "Activating..."; source venv/bin/activate; echo -e "  ${G}✔ Done${N}"
echo ""; echo "Upgrading pip..."; pip install --upgrade pip --quiet; echo -e "  ${G}✔ Done${N}"
echo ""; echo "Installing packages..."
for pkg in "numpy>=1.26.0" "pandas>=2.2.0" "pandas-ta>=0.4.67b0" "smartapi-python>=1.3.9" "pyotp>=2.9.0" "websocket-client>=1.7.0" "flask>=3.0.0" "flask-socketio>=5.3.0" "python-dotenv>=1.0.0" "schedule>=1.2.0" "requests>=2.31.0" "logzero>=1.7.0" "colorama>=0.4.6" "tabulate>=0.9.0" "python-dateutil>=2.9.0" "pytz>=2024.1"; do
    name=$(echo $pkg|cut -d">" -f1); echo -n "  $name... "
    pip install "$pkg" --prefer-binary --quiet && echo -e "${G}✔${N}" || echo -e "${R}✗${N}"
done
[ ! -f .env ] && cp .env.example .env && echo "  Created .env"
mkdir -p logs data
echo ""; python verify.py
echo ""; echo "============================================================"
echo " DONE! Next steps:"; echo " 1. nano .env   (fill in credentials)"
echo " 2. python verify.py"; echo " 3. python main.py --paper"
echo " 4. http://localhost:5000"; echo "============================================================"; echo ""
