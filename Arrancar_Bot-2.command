#!/bin/bash
# ════════════════════════════════════════════════
#   GERARDO_BOT — Launcher para macOS
# ════════════════════════════════════════════════

cd "$(dirname "$0")"

echo "═══════════════════════════════════════════"
echo "   GERARDO_BOT — Arrancando..."
echo "═══════════════════════════════════════════"
echo ""

# Activar entorno virtual
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✅ Entorno virtual activado (.venv)"
elif [ -d "venv" ]; then
    source venv/bin/activate
    echo "✅ Entorno virtual activado (venv)"
else
    echo "❌ No se encontró el entorno virtual"
    read -p "Apretá Enter para cerrar..."
    exit 1
fi

# Matar cualquier servidor previo en el puerto 8080
echo "🧹 Liberando puerto 8080..."
lsof -ti:8080 | xargs kill -9 2>/dev/null
sleep 1

# Levantar servidor HTTP en background
echo "🌐 Levantando servidor del dashboard en puerto 8080..."
python3 -m http.server 8080 > /dev/null 2>&1 &
SERVER_PID=$!

# Esperar hasta que el servidor responda (máximo 10 segundos)
echo "⏳ Esperando que el servidor esté listo..."
for i in {1..10}; do
    if curl -s http://localhost:8080 > /dev/null 2>&1; then
        echo "✅ Servidor activo"
        break
    fi
    sleep 1
done

# Abrir dashboard en el navegador
echo "📊 Abriendo dashboard..."
sleep 1
open "http://localhost:8080/dashboard.html"

echo ""
echo "🤖 Arrancando el bot..."
echo "   (Cerrá esta ventana para detener todo)"
echo ""

# Correr el bot
python3 main.py

# Al terminar, apagar servidor
echo ""
echo "⚠️  Bot detenido — apagando dashboard..."
kill $SERVER_PID 2>/dev/null
lsof -ti:8080 | xargs kill -9 2>/dev/null

echo "Listo. Apretá Enter para cerrar."
read
