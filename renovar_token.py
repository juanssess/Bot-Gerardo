"""
Renovación del token de Schwab con login en el navegador.
=========================================================
Abre la página de login de Schwab en el navegador, espera a que te loguees
y captura la respuesta sola (no hay que copiar ninguna URL).

El navegador va a mostrar un aviso de "conexión no privada" justo al final:
es este mismo script recibiendo la respuesta de Schwab en tu Mac
(https://127.0.0.1:8182). Apretá "Avanzado → Continuar".

El token nuevo se guarda en token_nuevo.json. El bot lo detecta y lo instala
solo, sin reiniciarse (si el bot está apagado, lo instala al arrancar).

Uso manual:
    python3 renovar_token.py              (espera hasta 30 min)
    python3 renovar_token.py --timeout 3600
"""

import sys
import json
import os
import argparse
import signal

from config import SCHWAB_APP_KEY, SCHWAB_APP_SECRET

CARPETA          = os.path.dirname(os.path.abspath(__file__))
CALLBACK_URL     = "https://127.0.0.1:8182"
TOKEN_NUEVO_PATH = os.path.join(CARPETA, "token_nuevo.json")


def _guardar_token(token, *args, **kwargs):
    tmp = TOKEN_NUEVO_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(token, f)
    os.replace(tmp, TOKEN_NUEVO_PATH)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30 * 60,
                        help="segundos que espera a que te loguees")
    args = parser.parse_args()

    # Si el bot nos cierra (terminate), salir limpio para que se apague el servidor del puerto 8182
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))

    # Si ya hay otro login esperando en el puerto 8182, no abrir otro: la respuesta de Schwab
    # le llegaría al proceso equivocado y el login fallaría.
    import socket
    with socket.socket() as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", 8182)) == 0:
            print("❌ Ya hay otra ventana de login de Schwab esperando (puerto 8182 ocupado).")
            print("   Usá la pestaña de Schwab más reciente del navegador.")
            return 2

    import schwab.auth
    try:
        schwab.auth.client_from_login_flow(
            api_key          = SCHWAB_APP_KEY,
            app_secret       = SCHWAB_APP_SECRET,
            callback_url     = CALLBACK_URL,
            token_path       = TOKEN_NUEVO_PATH,
            token_write_func = _guardar_token,
            callback_timeout = args.timeout,
            interactive      = False,
        )
    except schwab.auth.RedirectServerExitedError:
        print("❌ Ya hay otra ventana de login de Schwab esperando (puerto 8182 ocupado).")
        print("   Usá la pestaña de Schwab que ya está abierta en el navegador.")
        return 2
    except schwab.auth.RedirectTimeoutError:
        print("⏱ Se terminó el tiempo de espera sin login. Volvé a correrlo cuando quieras.")
        return 1

    print("✅ Token nuevo guardado. El bot lo instala solo en unos segundos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
