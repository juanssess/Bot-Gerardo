"""
Vigila el vencimiento del token de Schwab (dura 7 días).
- Cuando faltan menos de 24 h, abre solo el login de Schwab en el navegador
  (corre renovar_token.py en segundo plano) y avisa por dashboard y Telegram.
- Si nadie se loguea, lo vuelve a abrir cada 4 h.
- Cuando aparece el token nuevo, avisa que se renovó.
"""

import os
import sys
import time
import logging
import subprocess
from datetime import datetime

from schwab_api   import vencimiento_token
from telegram_bot import enviar_telegram

log = logging.getLogger(__name__)

CARPETA          = os.path.dirname(os.path.abspath(__file__))
AVISO_ANTES_SEG  = 24 * 3600    # cuánto antes del vencimiento se abre el login
REABRIR_CADA_SEG = 4 * 3600     # cuánto espera cada ventana de login antes de reabrir
MIN_ENTRE_INTENTOS_SEG = 5 * 60 # evita reabrir en loop si el login falla al arrancar

_proceso_login   = None
_ultima_apertura = 0.0
_vence_conocido  = None
_avisado_vencido = False


def _fecha(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")


def _login_abierto() -> bool:
    return _proceso_login is not None and _proceso_login.poll() is None


def _abrir_login():
    global _proceso_login, _ultima_apertura
    _proceso_login = subprocess.Popen(
        [sys.executable, os.path.join(CARPETA, "renovar_token.py"), "--timeout", str(REABRIR_CADA_SEG)],
        cwd=CARPETA,
    )
    _ultima_apertura = time.time()


def revisar_token() -> dict:
    """
    Llamar en cada vuelta del bucle. Devuelve:
        vence   → timestamp de vencimiento (0 si no hay token)
        vencido → True si ya no sirve
        aviso   → texto para el dashboard (None si está todo bien)
        evento  → texto para el log del dashboard cuando pasa algo (None si no)
    """
    global _vence_conocido, _avisado_vencido, _ultima_apertura

    ahora    = time.time()
    vence    = vencimiento_token()
    restante = vence - ahora
    vencido  = restante <= 0
    evento   = None

    # ── ¿Se renovó? ──
    if _vence_conocido is not None and vence > _vence_conocido + 60:
        evento = f"Token de Schwab renovado — vence el {_fecha(vence)}"
        log.info(evento)
        enviar_telegram(f"✅ <b>Token de Schwab renovado</b>\nVence el {_fecha(vence)}")
        _avisado_vencido = False
        _ultima_apertura = 0.0
        if _login_abierto():   # se renovó por otro lado (ej. Renovar_Token.command)
            _proceso_login.terminate()
    _vence_conocido = vence

    # ── Falta poco o ya venció → abrir login ──
    if restante < AVISO_ANTES_SEG and not _login_abierto() \
            and ahora - _ultima_apertura >= MIN_ENTRE_INTENTOS_SEG:
        primera_vez = _ultima_apertura == 0
        _abrir_login()
        evento = "Se abrió el login de Schwab en el navegador"
        log.warning(f"Token de Schwab vence el {_fecha(vence)} — abriendo login en el navegador")
        if primera_vez and not vencido:
            enviar_telegram(
                f"🔑 <b>El token de Schwab vence el {_fecha(vence)}</b>\n"
                f"Te abrí el login en el navegador de la Mac. Logueate cuando puedas."
            )

    if vencido and not _avisado_vencido:
        _avisado_vencido = True
        log.error("Token de Schwab VENCIDO — bot en pausa hasta que te loguees")
        enviar_telegram(
            "⛔ <b>Token de Schwab vencido</b>\n"
            "El bot está en pausa. Logueate en la pestaña de Schwab del navegador de la Mac "
            "(o doble clic en Renovar_Token.command) y sigue solo."
        )

    if vencido:
        aviso = ("Token de Schwab VENCIDO — bot en pausa. Logueate en la pestaña de Schwab "
                 "del navegador (o doble clic en Renovar_Token.command).")
    elif restante < AVISO_ANTES_SEG:
        aviso = (f"El token de Schwab vence el {_fecha(vence)}. Logueate en la pestaña de "
                 f"Schwab que se abrió en el navegador.")
    else:
        aviso = None

    return {"vence": vence, "vencido": vencido, "aviso": aviso, "evento": evento}
