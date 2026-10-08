"""
Telegram de Gerardo_Bot
=======================
Un solo bot de Telegram que puede hablar con VARIOS celulares (chats autorizados).
    - Los chats autorizados están en .env:  TELEGRAM_CHAT_ID=111111,222222
    - Todo mensaje del bot se manda a todos los chats autorizados.
    - Cualquier chat autorizado puede mandar comandos.

Vincular un celular nuevo:
    1. En la Mac: doble clic en Vincular_Telegram.command → muestra un código de 6 dígitos.
    2. En el celular nuevo: abrir el bot en Telegram, tocar "Iniciar" y mandar el código.
    Queda agregado al .env solo. El código vence a los 10 minutos.

Comandos:
    /estado      precio, posición y P&L
    /stop        pausa el bot y cierra la posición abierta
    /start       reactiva el bot
    /reporte     resumen desde que se prendió
    /vinculados  celulares que reciben los mensajes
    /ayuda       lista de comandos
"""

import json
import logging
import os
import random
import re
import threading
import time

import requests
from dotenv import dotenv_values

from config import TELEGRAM_TOKEN

log = logging.getLogger(__name__)

CARPETA      = os.path.dirname(os.path.abspath(__file__))
ENV_PATH     = os.path.join(CARPETA, ".env")
VINCULO_PATH = os.path.join(CARPETA, "telegram_vinculo.json")   # código pendiente de vinculación
API          = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
MINUTOS_CODIGO = 10


# ══════════════════════════════════════════════
#  CHATS AUTORIZADOS (se leen del .env; si el .env cambia, se recargan solos)
# ══════════════════════════════════════════════
_chats_cache = {"mtime": None, "lista": []}
_lock_env = threading.Lock()


def chats_autorizados() -> list:
    try:
        mtime = os.path.getmtime(ENV_PATH)
    except OSError:
        return _chats_cache["lista"]
    if mtime != _chats_cache["mtime"]:
        valor = dotenv_values(ENV_PATH).get("TELEGRAM_CHAT_ID") or ""
        _chats_cache["lista"] = [c.strip() for c in valor.split(",") if c.strip()]
        _chats_cache["mtime"] = mtime
    return list(_chats_cache["lista"])


def _guardar_chats(chats: list):
    """Reescribe solo la línea TELEGRAM_CHAT_ID del .env (el resto queda igual)."""
    with _lock_env:
        with open(ENV_PATH, encoding="utf-8") as f:
            lineas = f.read().splitlines()
        nueva = f"TELEGRAM_CHAT_ID={','.join(chats)}"
        for i, l in enumerate(lineas):
            if l.startswith("TELEGRAM_CHAT_ID="):
                lineas[i] = nueva
                break
        else:
            lineas.append(nueva)
        tmp = ENV_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n")
        os.replace(tmp, ENV_PATH)


def agregar_chat(chat_id: str):
    chats = chats_autorizados()
    if chat_id not in chats:
        _guardar_chats(chats + [chat_id])


def quitar_chat(chat_id: str) -> bool:
    chats = chats_autorizados()
    if chat_id not in chats:
        return False
    if len(chats) == 1:
        raise ValueError("No se puede quitar el único celular vinculado.")
    _guardar_chats([c for c in chats if c != chat_id])
    return True


# ══════════════════════════════════════════════
#  API DE TELEGRAM
# ══════════════════════════════════════════════
def _api(metodo: str, **params):
    """Llama a la API de Telegram. Devuelve el 'result' o None si falló."""
    try:
        r = requests.post(f"{API}/{metodo}", data=params, timeout=15)
        datos = r.json()
        if datos.get("ok"):
            return datos["result"]
        log.warning(f"[TELEGRAM] {metodo} falló: {datos.get('description')}")
    except requests.exceptions.Timeout:
        if metodo != "getUpdates":
            log.warning(f"[TELEGRAM] {metodo}: timeout")
    except Exception as e:
        log.warning(f"[TELEGRAM] {metodo}: {e}")
    return None


def _enviar_a(chat_id: str, texto: str) -> bool:
    return _api("sendMessage", chat_id=chat_id, text=texto, parse_mode="HTML") is not None


def enviar_telegram(mensaje: str) -> bool:
    """Manda el mensaje a TODOS los celulares vinculados. True si le llegó al menos a uno."""
    enviados = [_enviar_a(c, mensaje) for c in chats_autorizados()]
    return any(enviados)


def nombre_del_bot() -> str:
    yo = _api("getMe")
    return f"@{yo['username']}" if yo else "tu bot"


def nombre_de_chat(chat_id: str) -> str:
    c = _api("getChat", chat_id=chat_id)
    if not c:
        return chat_id
    nombre = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or c.get("title") or chat_id
    return f"{nombre} (@{c['username']})" if c.get("username") else nombre


# ══════════════════════════════════════════════
#  VINCULACIÓN DE CELULARES
# ══════════════════════════════════════════════
def crear_codigo() -> str:
    codigo = f"{random.SystemRandom().randint(0, 999999):06d}"
    with open(VINCULO_PATH, "w") as f:
        json.dump({"codigo": codigo, "vence": time.time() + MINUTOS_CODIGO * 60}, f)
    return codigo


def codigo_pendiente():
    try:
        with open(VINCULO_PATH) as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    if time.time() > datos.get("vence", 0):
        return None
    return datos.get("codigo")


def borrar_codigo():
    try:
        os.remove(VINCULO_PATH)
    except OSError:
        pass


def _intentar_vincular(chat_id: str, texto: str, nombre: str) -> bool:
    codigo = codigo_pendiente()
    enviado = re.sub(r"\D", "", texto)       # acepta "123456", "/vincular 123456", "123 456"
    if not codigo or enviado != codigo:
        return False
    agregar_chat(chat_id)
    borrar_codigo()
    log.info(f"[TELEGRAM] Celular vinculado: {nombre} (chat {chat_id})")
    _enviar_a(chat_id,
              "✅ <b>Celular vinculado a Gerardo_Bot</b>\n"
              "Desde ahora te llegan todos los avisos y podés mandar comandos.\n"
              "Mandá /ayuda para ver la lista.")
    for otro in chats_autorizados():
        if otro != chat_id:
            _enviar_a(otro, f"📱 Se vinculó un celular nuevo: <b>{nombre}</b>")
    return True


# ══════════════════════════════════════════════
#  COMANDOS
# ══════════════════════════════════════════════
_callback_stop   = None
_callback_estado = None
_pausado         = False


def registrar_callbacks(fn_stop, fn_estado):
    global _callback_stop, _callback_estado
    _callback_stop, _callback_estado = fn_stop, fn_estado


def esta_pausado() -> bool:
    return _pausado


def _num(v, fmt="{:,.2f}"):
    return fmt.format(v) if isinstance(v, (int, float)) else "—"


def _responder_comando(chat_id: str, texto: str, nombre: str):
    global _pausado
    comando = texto.strip().split()[0].split("@")[0].lower()

    if comando == "/estado":
        if not _callback_estado:
            return _enviar_a(chat_id, "⏳ El bot todavía está arrancando…")
        i = _callback_estado()
        _enviar_a(chat_id,
            f"📊 <b>Estado de Gerardo_Bot</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Bot:         {'⏸ PAUSADO' if _pausado else '▶️ Activo'}\n"
            f"💵 Precio:      {_num(i.get('precio'))}\n"
            f"📌 Posición:    {i.get('posicion') or 'ninguna'}\n"
            f"📥 Entrada:     {_num(i.get('entrada'))}\n"
            f"💰 P&L:         ${i.get('pnl', 0):+,.2f}\n"
            f"📊 Operaciones: {i.get('ops', 0)}/{i.get('max_ops', '—')}\n"
            f"🛡 Pérdida:     ${i.get('perdida', 0):,.2f} / ${i.get('max_perdida', 0):,.0f}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 EMA 7:  {_num(i.get('ema7'))}\n"
            f"📉 EMA 10: {_num(i.get('ema10'))}")

    elif comando == "/stop":
        if _pausado:
            return _enviar_a(chat_id, "⏸ El bot ya estaba pausado. Mandá /start para reactivarlo.")
        _pausado = True
        if _callback_stop:
            _callback_stop()
        log.info(f"[TELEGRAM] Bot pausado por /stop de {nombre}")
        enviar_telegram(f"⏸ <b>Bot pausado</b> por {nombre}.\n"
                        f"Si había posición abierta, se cerró. Mandá /start para reactivarlo.")

    elif comando == "/start":
        if not _pausado:
            return _enviar_a(chat_id, "▶️ El bot ya está activo. Mandá /ayuda para ver los comandos.")
        _pausado = False
        log.info(f"[TELEGRAM] Bot reactivado por /start de {nombre}")
        enviar_telegram(f"▶️ <b>Bot reactivado</b> por {nombre}.\nBuscando el próximo cruce.")

    elif comando == "/reporte":
        if not _callback_estado:
            return _enviar_a(chat_id, "⏳ El bot todavía está arrancando…")
        i = _callback_estado()
        pnl = i.get("pnl", 0)
        _enviar_a(chat_id,
            f"{'🟢' if pnl > 0 else '🔴' if pnl < 0 else '⚪'} <b>Reporte desde que se prendió</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 P&L neto:     ${pnl:+,.2f}\n"
            f"📊 Operaciones:  {i.get('ops', 0)}\n"
            f"🟢 Compras:      {i.get('buys', 0)}\n"
            f"🔴 Ventas:       {i.get('sells', 0)}\n"
            f"🛡 Pérdida:      ${i.get('perdida', 0):,.2f}")

    elif comando == "/vinculados":
        lineas = [f"• {nombre_de_chat(c)}{'  ← vos' if c == chat_id else ''}" for c in chats_autorizados()]
        _enviar_a(chat_id, "📱 <b>Celulares vinculados</b>\n" + "\n".join(lineas) +
                  "\n\nPara sumar otro: en la Mac, doble clic en Vincular_Telegram.command.")

    elif comando == "/ayuda":
        _enviar_a(chat_id,
            "🤖 <b>Comandos de Gerardo_Bot</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "/estado      → precio, posición y P&L\n"
            "/stop        → pausa el bot y cierra la posición\n"
            "/start       → reactiva el bot\n"
            "/reporte     → resumen desde que se prendió\n"
            "/vinculados  → celulares que reciben los avisos\n"
            "/ayuda       → esta lista")

    else:
        _enviar_a(chat_id, f"❓ No conozco «{texto[:40]}». Mandá /ayuda para ver los comandos.")


def procesar_mensaje(mensaje: dict) -> bool:
    """Procesa un mensaje recibido. Devuelve True si vinculó un celular."""
    texto   = (mensaje.get("text") or "").strip()
    chat    = mensaje.get("chat", {})
    chat_id = str(chat.get("id", ""))
    nombre  = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat_id
    if not texto or not chat_id:
        return False

    if chat_id not in chats_autorizados():
        if _intentar_vincular(chat_id, texto, nombre):
            return True
        log.warning(f"[TELEGRAM] Mensaje de un chat no vinculado: {nombre} ({chat_id}): {texto[:40]!r}")
        _enviar_a(chat_id,
            "🔒 Este celular todavía no está vinculado a Gerardo_Bot.\n\n"
            "Para vincularlo: en la Mac hacé doble clic en <b>Vincular_Telegram.command</b> "
            "y mandá acá el código de 6 dígitos que te muestra.")
        return False

    if texto.startswith("/"):
        log.info(f"[TELEGRAM] Comando {texto!r} de {nombre}")
        _responder_comando(chat_id, texto, nombre)
    return False


# ══════════════════════════════════════════════
#  ESCUCHA DE MENSAJES (long polling)
# ══════════════════════════════════════════════
def descartar_pendientes() -> int:
    """
    Ignora los mensajes que llegaron mientras el bot estaba apagado
    (si no, un /stop viejo se ejecutaría al prenderlo). Devuelve el offset a usar.
    """
    ultimos = _api("getUpdates", offset=-1, timeout=0)
    return ultimos[-1]["update_id"] + 1 if ultimos else 0


def escuchar(hasta=None, al_vincular=None):
    """
    Loop de mensajes. Corre para siempre (hilo del bot) o hasta que hasta() devuelva True
    (lo usa vincular_telegram.py cuando el bot está apagado).
    """
    offset = descartar_pendientes()
    while not (hasta and hasta()):
        updates = _api_get_updates(offset)
        if updates is None:
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                if procesar_mensaje(u.get("message") or {}) and al_vincular:
                    al_vincular()
            except Exception as e:
                log.warning(f"[TELEGRAM] Error procesando mensaje: {e}")


def _api_get_updates(offset: int):
    """getUpdates con long polling de 25 s (el timeout HTTP tiene que ser mayor)."""
    try:
        r = requests.post(f"{API}/getUpdates", timeout=35,
                          data={"offset": offset, "timeout": 25, "allowed_updates": '["message"]'})
        datos = r.json()
        return datos["result"] if datos.get("ok") else None
    except requests.exceptions.Timeout:
        return []
    except Exception as e:
        log.warning(f"[TELEGRAM] Error escuchando mensajes: {e}")
        return None


def iniciar_listener():
    hilo = threading.Thread(target=escuchar, daemon=True, name="telegram")
    hilo.start()
    log.info(f"[TELEGRAM] Escuchando comandos · {len(chats_autorizados())} celular(es) vinculado(s)")
    return hilo
