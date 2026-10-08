"""
Vincular un celular a Gerardo_Bot (Telegram)
============================================
    python3 vincular_telegram.py              → muestra un código para vincular un celular nuevo
    python3 vincular_telegram.py --lista      → lista los celulares vinculados
    python3 vincular_telegram.py --quitar ID  → desvincula un celular (ID de la lista)

Funciona con el bot prendido o apagado:
    - prendido: el bot recibe el código y vincula el celular; este script solo espera la confirmación
    - apagado:  este script escucha Telegram él mismo hasta recibir el código
"""

import argparse
import fcntl
import logging
import os
import sys
import time

import telegram_bot as tg

LOCK_PATH = os.path.join(tg.CARPETA, "bot.lock")


def bot_prendido():
    """Devuelve (prendido, lock). Si el bot está apagado, nos quedamos con el lock mientras vinculamos."""
    f = open(LOCK_PATH, "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False, f
    except BlockingIOError:
        f.close()
        return True, None


def listar():
    chats = tg.chats_autorizados()
    print(f"\n📱 Celulares vinculados ({len(chats)}):\n")
    for c in chats:
        print(f"   {c:>14}   {tg.nombre_de_chat(c)}")
    print()


def vincular():
    antes = set(tg.chats_autorizados())
    codigo = tg.crear_codigo()
    bot = tg.nombre_del_bot()

    print("\n══════════════════════════════════════════════")
    print("   VINCULAR UN CELULAR A GERARDO_BOT")
    print("══════════════════════════════════════════════\n")
    print(f"   1. En el celular nuevo abrí Telegram y buscá  {bot}")
    print(f"   2. Tocá «Iniciar» (o «Start»)")
    print(f"   3. Mandale este código:\n")
    print(f"              {codigo[:3]} {codigo[3:]}\n")
    print(f"   El código vence en {tg.MINUTOS_CODIGO} minutos. Esperando…\n")

    prendido, lock = bot_prendido()
    vence = time.time() + tg.MINUTOS_CODIGO * 60
    nuevo = lambda: set(tg.chats_autorizados()) - antes

    if prendido:
        # El bot recibe el mensaje y vincula; acá solo miramos si apareció el chat nuevo en .env
        while not nuevo() and time.time() < vence:
            time.sleep(2)
    else:
        tg.escuchar(hasta=lambda: bool(nuevo()) or time.time() > vence)
        lock.close()

    agregados = nuevo()
    if agregados:
        for c in agregados:
            print(f"✅ Listo: se vinculó {tg.nombre_de_chat(c)}. Ya le llegan todos los avisos.\n")
        return 0
    tg.borrar_codigo()
    print("⏱ Se venció el código sin recibirlo. Volvé a abrir Vincular_Telegram.command para probar otra vez.\n")
    return 1


def quitar(chat_id: str):
    try:
        if tg.quitar_chat(chat_id):
            print(f"✅ Desvinculado {chat_id}. Ya no le llegan avisos ni puede mandar comandos.\n")
            return 0
        print(f"No hay ningún celular vinculado con ID {chat_id}. Mirá la lista con --lista.\n")
    except ValueError as e:
        print(f"❌ {e}\n")
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--lista", action="store_true")
    p.add_argument("--quitar", metavar="ID")
    a = p.parse_args()
    if a.lista:
        listar()
        sys.exit(0)
    if a.quitar:
        sys.exit(quitar(a.quitar))
    sys.exit(vincular())
