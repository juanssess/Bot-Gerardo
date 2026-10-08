#!/bin/bash
# ════════════════════════════════════════════════
#   GERARDO_BOT — Renovar token de Schwab
#   Abre el login en el navegador; logueate y listo.
#   Si el bot está corriendo, toma el token nuevo solo.
# ════════════════════════════════════════════════

cd "$(dirname "$0")"
source .venv/bin/activate

echo "🔑 Abriendo el login de Schwab en el navegador..."
echo "   Al final vas a ver 'conexión no privada': apretá Avanzado → Continuar."
echo ""
python3 renovar_token.py

echo ""
read -p "Apretá Enter para cerrar..."
