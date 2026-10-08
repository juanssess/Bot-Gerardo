#!/bin/bash
# ════════════════════════════════════════════════
#   GERARDO_BOT — Vincular un celular a Telegram
#   Muestra un código; mandalo al bot desde el celular nuevo.
# ════════════════════════════════════════════════

cd "$(dirname "$0")"
source .venv/bin/activate

python3 vincular_telegram.py 2>/dev/null
python3 vincular_telegram.py --lista 2>/dev/null

read -p "Apretá Enter para cerrar..."
