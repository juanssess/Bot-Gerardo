"""
Launcher simple para Mac.
Levanta servidor del dashboard, abre el navegador y corre el bot.

Uso:
    python3 arrancar.py
"""
import http.server
import socketserver
import threading
import webbrowser
import time
import os
import sys

PORT = 8080

# Ir a la carpeta donde está este archivo
os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("═══════════════════════════════════════════")
print("   GERARDO_BOT — Arrancando...")
print("═══════════════════════════════════════════")
print()

# Levantar servidor HTTP en un thread aparte
def correr_servidor():
    Handler = http.server.SimpleHTTPRequestHandler
    # silenciar logs del servidor
    Handler.log_message = lambda *a, **kw: None
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()

server_thread = threading.Thread(target=correr_servidor, daemon=True)
server_thread.start()
print(f"Servidor del dashboard en http://localhost:{PORT}")

# Esperar que arranque
time.sleep(2)

# Abrir dashboard
url = f"http://localhost:{PORT}/dashboard.html"
print(f"Abriendo dashboard: {url}")
webbrowser.open(url)

time.sleep(1)
print()
print("Arrancando el bot... (Ctrl+C para detener)")
print()

# Importar y correr el bot
try:
    import main
    main.main()
except KeyboardInterrupt:
    print("\nBot detenido manualmente.")
except Exception as e:
    print(f"\nError: {e}")
    input("Apretá Enter para cerrar...")