"""
Autenticación Schwab — versión en DOS PASOS, sin input() que se cuelga.

═══════════════════════════════════════════════════════════════
PASO 1 — generar el link de login:

    python3 autenticar_schwab.py

  Te imprime un link. Abrilo en el navegador, logueate y autorizá.
  Vas a terminar en una página de "conexión no privada" o en blanco.
  Copiá la URL COMPLETA de la barra del navegador (empieza con
  https://127.0.0.1:8182/?code=...).

═══════════════════════════════════════════════════════════════
PASO 2 — pegar la URL para generar el token (ENTRE COMILLAS):

    python3 autenticar_schwab.py "https://127.0.0.1:8182/?code=...&session=..."

  Eso genera token.json y listo.
═══════════════════════════════════════════════════════════════
"""

import sys
import json
import schwab.auth
from config import SCHWAB_APP_KEY, SCHWAB_APP_SECRET

CALLBACK_URL  = "https://127.0.0.1:8182"
TOKEN_PATH    = "token.json"
CONTEXT_PATH  = ".auth_context.json"   # archivo temporal entre paso 1 y 2


def paso1_generar_link():
    ctx = schwab.auth.get_auth_context(SCHWAB_APP_KEY, CALLBACK_URL)

    # Guardar el state para el paso 2
    with open(CONTEXT_PATH, "w") as f:
        json.dump({"state": ctx.state, "callback_url": ctx.callback_url}, f)

    print("=" * 64)
    print("PASO 1 — ABRÍ ESTE LINK EN EL NAVEGADOR Y LOGUEATE:")
    print("=" * 64)
    print()
    print(ctx.authorization_url)
    print()
    print("=" * 64)
    print("Cuando termines, copiá la URL final de la barra del navegador")
    print("(la que arranca con https://127.0.0.1:8182/?code=...)")
    print()
    print("Y después corré, CON LA URL ENTRE COMILLAS:")
    print()
    print('   python3 autenticar_schwab.py "PEGÁ_LA_URL_ACÁ"')
    print("=" * 64)


def paso2_generar_token(received_url: str):
    # Recuperar el state guardado en el paso 1
    try:
        with open(CONTEXT_PATH) as f:
            datos = json.load(f)
        state = datos["state"]
        callback_url = datos["callback_url"]
    except FileNotFoundError:
        print("ERROR: No encontré el archivo del paso 1.")
        print("Corré primero 'python3 autenticar_schwab.py' sin argumentos.")
        return

    # Reconstruir el auth_context
    ctx = schwab.auth.AuthContext(
        callback_url      = callback_url,
        authorization_url = None,
        state             = state,
    )

    def guardar_token(token, *args, **kwargs):
        with open(TOKEN_PATH, "w") as f:
            json.dump(token, f)

    schwab.auth.client_from_received_url(
        api_key         = SCHWAB_APP_KEY,
        app_secret      = SCHWAB_APP_SECRET,
        auth_context    = ctx,
        received_url    = received_url,
        token_write_func= guardar_token,
    )

    print("=" * 64)
    print("✅ TOKEN GENERADO CORRECTAMENTE en token.json")
    print("Ya podés arrancar el bot.")
    print("=" * 64)


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        paso2_generar_token(sys.argv[1])
    else:
        paso1_generar_link()