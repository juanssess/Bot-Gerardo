"""
Módulo de comandos Telegram para Gerardo_Bot.
Permite controlar el bot desde el celular en tiempo real.

Comandos disponibles:
    /estado   → precio actual, posición, P&L del día
    /stop     → cierra posición abierta y pausa el bot
    /start    → reactiva el bot si estaba pausado
    /reporte  → resumen del día en cualquier momento
    /ayuda    → lista de comandos
"""

import threading
import requests
import time
import logging
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)

# ID del chat autorizado — solo este chat puede mandar comandos
CHAT_ID_AUTORIZADO = str(TELEGRAM_CHAT_ID)

# Estado del listener
_ultimo_update_id = 0
_bot_pausado       = False
_callback_stop     = None  # función que se llama cuando se manda /stop
_callback_estado   = None  # función que devuelve el estado actual


def registrar_callbacks(fn_stop, fn_estado):
    """Registra las funciones del bot principal para ejecutar comandos."""
    global _callback_stop, _callback_estado
    _callback_stop   = fn_stop
    _callback_estado = fn_estado


def esta_pausado() -> bool:
    return _bot_pausado


def enviar_respuesta(chat_id: str, mensaje: str):
    """Envía una respuesta al chat."""
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        log.warning(f"[TELEGRAM CMD] Error enviando respuesta: {e}")


def procesar_comando(chat_id: str, texto: str):
    """Procesa un comando recibido por Telegram."""
    global _bot_pausado

    # Verificar que el comando viene del chat autorizado
    if str(chat_id) != CHAT_ID_AUTORIZADO:
        enviar_respuesta(chat_id, "⛔ No estás autorizado para controlar este bot.")
        log.warning(f"[TELEGRAM CMD] Intento no autorizado desde chat_id: {chat_id}")
        return

    comando = texto.strip().lower().split()[0]

    if comando == "/estado":
        if _callback_estado:
            info = _callback_estado()
            pausado_txt = "⏸ PAUSADO" if _bot_pausado else "▶️ Activo"
            enviar_respuesta(chat_id,
                f"📊 <b>Estado de Gerardo_Bot</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 Bot:          {pausado_txt}\n"
                f"💵 Precio:       ${info.get('precio', '—')}\n"
                f"📌 Posición:     {info.get('posicion', 'NINGUNA')}\n"
                f"📥 Entrada:      {('$' + str(info.get('entrada'))) if info.get('entrada') else '—'}\n"
                f"💰 P&L día:      ${info.get('pnl', 0):+.2f}\n"
                f"📊 Operaciones:  {info.get('ops', 0)}/{info.get('max_ops', 10)}\n"
                f"🛡 Pérdida día:  ${info.get('perdida', 0):.2f}/${info.get('max_perdida', 500):.0f}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📈 EMA 6:  {info.get('ema6', '—')}\n"
                f"📉 EMA 10: {info.get('ema10', '—')}"
            )
        else:
            enviar_respuesta(chat_id, "⚠️ Bot todavía iniciando...")

    elif comando == "/stop":
        if _bot_pausado:
            enviar_respuesta(chat_id, "⏸ El bot ya estaba pausado.")
        else:
            _bot_pausado = True
            enviar_respuesta(chat_id,
                "⏸ <b>Bot pausado.</b>\n"
                "Se cerró la posición abierta si había una.\n"
                "Mandá /start para reactivar."
            )
            if _callback_stop:
                _callback_stop()
            log.info("[TELEGRAM CMD] Bot pausado por comando /stop")

    elif comando == "/start":
        if not _bot_pausado:
            enviar_respuesta(chat_id, "▶️ El bot ya estaba activo.")
        else:
            _bot_pausado = False
            enviar_respuesta(chat_id,
                "▶️ <b>Bot reactivado.</b>\n"
                "Monitoreando el mercado — próximo cruce abrirá posición."
            )
            log.info("[TELEGRAM CMD] Bot reactivado por comando /start")

    elif comando == "/reporte":
        if _callback_estado:
            info = _callback_estado()
            pnl  = info.get('pnl', 0)
            emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
            enviar_respuesta(chat_id,
                f"{emoji} <b>Reporte del día</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 P&L:          ${pnl:+.2f}\n"
                f"📊 Operaciones:  {info.get('ops', 0)}\n"
                f"🟢 Compras:      {info.get('buys', 0)}\n"
                f"🔴 Ventas:       {info.get('sells', 0)}\n"
                f"🛡 Pérdida día:  ${info.get('perdida', 0):.2f}"
            )
        else:
            enviar_respuesta(chat_id, "⚠️ Bot todavía iniciando...")

    elif comando == "/ayuda":
        enviar_respuesta(chat_id,
            "🤖 <b>Comandos de Gerardo_Bot</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "/estado  → precio, posición y P&L\n"
            "/stop    → pausa el bot y cierra posición\n"
            "/start   → reactiva el bot\n"
            "/reporte → resumen del día\n"
            "/ayuda   → esta lista"
        )

    else:
        enviar_respuesta(chat_id,
            f"❓ Comando no reconocido: {texto}\n"
            "Mandá /ayuda para ver los comandos disponibles."
        )


def escuchar_comandos():
    """
    Loop que escucha mensajes de Telegram en segundo plano.
    Corre en un thread separado para no bloquear el bot.
    """
    global _ultimo_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

    log.info("[TELEGRAM CMD] Listener de comandos iniciado.")

    while True:
        try:
            resp = requests.get(url, params={
                "offset":  _ultimo_update_id + 1,
                "timeout": 30,
            }, timeout=35)

            if resp.status_code != 200:
                time.sleep(5)
                continue

            data = resp.json()
            for update in data.get("result", []):
                _ultimo_update_id = update["update_id"]
                mensaje = update.get("message", {})
                texto   = mensaje.get("text", "")
                chat_id = str(mensaje.get("chat", {}).get("id", ""))

                if texto.startswith("/"):
                    log.info(f"[TELEGRAM CMD] Comando recibido: '{texto}' de chat_id: {chat_id}")
                    procesar_comando(chat_id, texto)

        except requests.exceptions.Timeout:
            pass  # normal con long polling
        except Exception as e:
            log.warning(f"[TELEGRAM CMD] Error en listener: {e}")
            time.sleep(5)


def iniciar_listener():
    """Arranca el listener de comandos en un thread separado."""
    t = threading.Thread(target=escuchar_comandos, daemon=True)
    t.start()
    log.info("[TELEGRAM CMD] Thread de comandos iniciado.")
    return t