"""
Gerardo_Bot — EMA 7/10 con confirmación en vela siguiente
=========================================================
VELAS REALES (tamaño = VELA_SEG en config.py, hoy 1 minuto):
    - Al arrancar se cargan velas de Schwab (historial inicial), del mismo
      tamaño que las del vivo.
    - Después, el bot junta los precios realtime de Schwab en cubetas de
      VELA_SEG y arma el OHLC real de cada vela. La EMA se recalcula para
      DECISIONES sólo cuando una vela CIERRA (como en ThinkorSwim).
    - El dashboard muestra las EMAs EN VIVO (incluyendo la vela en curso),
      así siguen de cerca a las de ThinkorSwim.

Lógica de ENTRADA:
    - EMA 7 cruza EMA 10 hacia arriba  → se marca señal COMPRAR pendiente
    - EMA 7 cruza EMA 10 hacia abajo   → se marca señal VENDER  pendiente
    - La orden NO se abre en el momento del cruce.
      Se espera a la VELA SIGUIENTE y, si el cruce sigue confirmado
      (EMA7 sigue del lado correcto de la EMA10), recién ahí entra.
    - Si en la vela siguiente el cruce se dio vuelta, se descarta.

Lógica de SALIDA (ambas a 4 puntos = 16 ticks en /MES):
    - Take profit: +TAKE_PROFIT_PUNTOS
    - Stop loss:   -STOP_LOSS_PUNTOS
    - No hay salida por cruce contrario: una vez adentro, solo TP o SL.

Modo PAPER forzado (schwab_api nunca manda órdenes reales).
"""

import time
import logging
import json
import os
from datetime import datetime, date

from config import (
    validar_config, TIMEFRAME_SEG, MAX_PERDIDA_DIARIA_USD, MAX_OPERACIONES_DIA,
    SIMBOLO, TAKE_PROFIT_PUNTOS, STOP_LOSS_PUNTOS, get_valor_por_punto, VELA_SEG,
)
from estrategia        import calcular_emas
from notificaciones    import enviar_telegram
from schwab_api        import obtener_precio_actual, obtener_historial_ohlc, ejecutar_orden
from reporte           import enviar_reporte_diario
from telegram_comandos import iniciar_listener, registrar_callbacks, esta_pausado
from control_token     import revisar_token

ESTADO_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado.json")
VALOR_PUNTO = get_valor_por_punto()

# ═════════════════════════════════════════════════════════════════
#  HORARIO DE OPERACIÓN — 19:00 a 17:30 hora Argentina
# ═════════════════════════════════════════════════════════════════
HORA_APERTURA = "19:00"
HORA_CIERRE   = "17:30"

# ═════════════════════════════════════════════════════════════════
#  LOGGING
# ═════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════
#  ESTADO DEL DÍA
# ═════════════════════════════════════════════════════════════════
estado = {
    "fecha_actual":       date.today(),
    "perdida_acumulada":  0.0,
    "operaciones_hoy":    0,
    "posicion_abierta":   None,    # "LONG", "SHORT" o None
    "precio_entrada":     None,
    "stop_loss_precio":   None,
    "take_profit_precio": None,
    "senal_pendiente":    None,    # "COMPRAR"/"VENDER" esperando la vela siguiente
    "minuto_senal":       None,    # minuto (HH:MM) en que se detectó el cruce
    "pnl_paper":          0.0,
    "buys_hoy":           0,
    "sells_hoy":          0,
    "telegram_ok":        True,
    "modo":               "PAPER",
    "velas_procesadas":   0,
    "reporte_enviado":    False,
    "token_vence":        None,    # "dd/mm HH:MM" en que vence el token de Schwab
    "aviso_token":        None,    # texto para el dashboard si falta poco o venció
    "token_vencido":      False,
}

operaciones_dia = []
log_dashboard   = []


# ═════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════
def agregar_log_dashboard(tipo: str, precio, mensaje: str):
    hora = datetime.now().strftime("%H:%M:%S")
    log_dashboard.insert(0, {"hora": hora, "tipo": tipo, "precio": precio, "mensaje": mensaje})
    if len(log_dashboard) > 50:
        log_dashboard.pop()


def guardar_estado(precio: float, resultado_ema: dict, senal: str, historial_close: list):
    hora = datetime.now().strftime("%H:%M:%S")
    ema7  = resultado_ema.get("ema7_actual")
    ema10 = resultado_ema.get("ema10_actual")
    datos = {
        "timestamp":          hora,
        "simbolo":            SIMBOLO,
        "modo":               estado["modo"],
        "precio_actual":      precio,
        # El dashboard lee "ema6"/"ema10": le pasamos la EMA7 bajo "ema6" (cosmético).
        "ema6":               ema7,
        "ema7":               ema7,
        "ema10":              ema10,
        "adx":                resultado_ema.get("adx"),
        "señal":              senal,
        "posicion_abierta":   estado["posicion_abierta"],
        "precio_entrada":     estado["precio_entrada"],
        "stop_loss_precio":   estado["stop_loss_precio"],
        "take_profit_precio": estado["take_profit_precio"],
        "operaciones_hoy":    estado["operaciones_hoy"],
        "max_operaciones":    MAX_OPERACIONES_DIA,
        "perdida_acumulada":  round(estado["perdida_acumulada"], 2),
        "max_perdida":        MAX_PERDIDA_DIARIA_USD,
        "pnl_paper":          round(estado["pnl_paper"], 2),
        "buys_hoy":           estado["buys_hoy"],
        "sells_hoy":          estado["sells_hoy"],
        "telegram_ok":        estado["telegram_ok"],
        "velas_procesadas":   estado["velas_procesadas"],
        "historial_precios":  historial_close[-40:],
        "log":                log_dashboard[:50],
        "take_profit_puntos": TAKE_PROFIT_PUNTOS,
        "stop_loss_puntos":   STOP_LOSS_PUNTOS,
        "token_vence":        estado["token_vence"],
        "aviso_token":        estado["aviso_token"],
        "token_vencido":      estado["token_vencido"],
    }
    try:
        tmp = ESTADO_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(tmp, ESTADO_JSON)
    except Exception as e:
        log.warning(f"No se pudo escribir estado.json: {e}")


def resetear_estado_si_nuevo_dia():
    hoy = date.today()
    if estado["fecha_actual"] != hoy:
        log.info("Nuevo día — reseteando contadores.")
        estado.update({
            "fecha_actual": hoy, "perdida_acumulada": 0.0,
            "operaciones_hoy": 0, "buys_hoy": 0, "sells_hoy": 0,
            "pnl_paper": 0.0,
        })
        operaciones_dia.clear()
        agregar_log_dashboard("INFO", None, "Nuevo día — contadores reseteados")


def actualizar_token() -> bool:
    """Revisa el token de Schwab, actualiza el estado para el dashboard. Devuelve True si venció."""
    info = revisar_token()
    estado["token_vence"]   = datetime.fromtimestamp(info["vence"]).strftime("%d/%m %H:%M") if info["vence"] else None
    estado["aviso_token"]   = info["aviso"]
    estado["token_vencido"] = info["vencido"]
    if info["evento"]:
        agregar_log_dashboard("WARN" if info["vencido"] else "INFO", None, info["evento"])
    return info["vencido"]


def circuit_breaker_activo() -> bool:
    if estado["perdida_acumulada"] >= MAX_PERDIDA_DIARIA_USD:
        log.warning(f"CIRCUIT BREAKER: pérdida ${estado['perdida_acumulada']:.2f} >= ${MAX_PERDIDA_DIARIA_USD}")
        agregar_log_dashboard("WARN", None, f"Circuit breaker — pérdida ${estado['perdida_acumulada']:.2f}")
        return True
    if estado["operaciones_hoy"] >= MAX_OPERACIONES_DIA:
        log.warning(f"CIRCUIT BREAKER: {estado['operaciones_hoy']} ops >= {MAX_OPERACIONES_DIA}")
        agregar_log_dashboard("WARN", None, "Circuit breaker — máximo de operaciones alcanzado")
        return True
    return False


def es_horario_operacion() -> bool:
    """Opera de 19:00 a 17:30 (Argentina). Cerrado entre 17:30 y 19:00."""
    ahora = datetime.now().strftime("%H:%M")
    return ahora >= HORA_APERTURA or ahora < HORA_CIERRE


# ═════════════════════════════════════════════════════════════════
#  CERRAR POSICIÓN
# ═════════════════════════════════════════════════════════════════
def cerrar_posicion(precio: float, motivo: str):
    pos            = estado["posicion_abierta"]
    precio_entrada = estado["precio_entrada"]

    if pos == "LONG":
        resultado   = (precio - precio_entrada) * VALOR_PUNTO
        lado_cierre = "SELL"
    else:
        resultado   = (precio_entrada - precio) * VALOR_PUNTO
        lado_cierre = "BUY"

    estado["pnl_paper"] += resultado
    if resultado < 0:
        estado["perdida_acumulada"] += abs(resultado)

    operaciones_dia.append({
        "entrada":   precio_entrada,
        "salida":    precio,
        "posicion":  pos,
        "resultado": round(resultado, 2),
        "motivo":    motivo,
        "hora":      datetime.now().strftime("%H:%M:%S"),
    })

    emoji    = "✅" if resultado > 0 else "❌"
    tipo_log = "VENTA" if lado_cierre == "SELL" else "COMPRA"
    agregar_log_dashboard(tipo_log, precio, f"{motivo} · {pos} cerrado · P&L: ${resultado:+.2f}")

    enviar_telegram(
        f"{emoji} <b>POSICIÓN CERRADA — {motivo}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Tipo:       {pos}\n"
        f"📥 Entrada:    ${precio_entrada:.2f}\n"
        f"📤 Salida:     ${precio:.2f}\n"
        f"💰 Resultado:  ${resultado:+.2f}\n"
        f"📊 P&L día:    ${estado['pnl_paper']:+.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Operaciones hoy: {estado['operaciones_hoy']}/{MAX_OPERACIONES_DIA}"
    )

    log.info(f"[{motivo}] {pos} | Entrada: ${precio_entrada:.2f} | Salida: ${precio:.2f} | P&L: ${resultado:+.2f}")
    ejecutar_orden(lado_cierre)

    estado.update({
        "posicion_abierta":   None,
        "precio_entrada":     None,
        "stop_loss_precio":   None,
        "take_profit_precio": None,
    })


# ═════════════════════════════════════════════════════════════════
#  VERIFICAR TAKE PROFIT / STOP LOSS
# ═════════════════════════════════════════════════════════════════
def verificar_tp_sl(precio: float) -> str:
    """Devuelve 'TAKE', 'STOP' o None."""
    if not estado["posicion_abierta"] or estado["precio_entrada"] is None:
        return None

    pos = estado["posicion_abierta"]
    tp  = estado["take_profit_precio"]
    sl  = estado["stop_loss_precio"]

    if pos == "LONG":
        if sl is not None and precio <= sl:
            return "STOP"
        if tp is not None and precio >= tp:
            return "TAKE"
    else:  # SHORT
        if sl is not None and precio >= sl:
            return "STOP"
        if tp is not None and precio <= tp:
            return "TAKE"
    return None


# ═════════════════════════════════════════════════════════════════
#  ABRIR POSICIÓN
# ═════════════════════════════════════════════════════════════════
def abrir_posicion(senal: str, precio: float, resultado_ema: dict):
    hora = datetime.now().strftime("%H:%M:%S")
    lado = "BUY"  if senal == "COMPRAR" else "SELL"
    pos  = "LONG" if senal == "COMPRAR" else "SHORT"

    if pos == "LONG":
        tp = round(precio + TAKE_PROFIT_PUNTOS, 2)
        sl = round(precio - STOP_LOSS_PUNTOS, 2) if STOP_LOSS_PUNTOS > 0 else None
    else:
        tp = round(precio - TAKE_PROFIT_PUNTOS, 2)
        sl = round(precio + STOP_LOSS_PUNTOS, 2) if STOP_LOSS_PUNTOS > 0 else None

    ejecutar_orden(lado)

    estado["operaciones_hoy"]    += 1
    estado["posicion_abierta"]    = pos
    estado["precio_entrada"]      = precio
    estado["take_profit_precio"]  = tp
    estado["stop_loss_precio"]    = sl

    if senal == "COMPRAR":
        estado["buys_hoy"] += 1
        agregar_log_dashboard("COMPRA", precio, f"Cruce alcista confirmado EMA7/10 · TP:${tp} · SL:${sl}")
    else:
        estado["sells_hoy"] += 1
        agregar_log_dashboard("VENTA", precio, f"Cruce bajista confirmado EMA7/10 · TP:${tp} · SL:${sl}")

    emoji  = "🟢" if senal == "COMPRAR" else "🔴"
    titulo = "COMPRA — Cruce Alcista (confirmado)" if senal == "COMPRAR" else "VENTA — Cruce Bajista (confirmado)"
    sl_txt = f"${sl:.2f}  ({STOP_LOSS_PUNTOS} pts)" if sl is not None else "desactivado"

    enviado = enviar_telegram(
        f"{emoji} <b>{titulo}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Símbolo:     {SIMBOLO}\n"
        f"💵 Entrada:     ${precio:.2f}\n"
        f"📦 Contratos:   1\n"
        f"📈 EMA 7:       {resultado_ema.get('ema7_actual')}\n"
        f"📉 EMA 10:      {resultado_ema.get('ema10_actual')}\n"
        f"🎯 Take profit: ${tp:.2f}  ({TAKE_PROFIT_PUNTOS} pts)\n"
        f"🛑 Stop loss:   {sl_txt}\n"
        f"🕐 Hora:        {hora}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Operaciones hoy: {estado['operaciones_hoy']}/{MAX_OPERACIONES_DIA}"
    )
    estado["telegram_ok"] = enviado
    log.info(f"[ENTRADA {pos}] ${precio:.2f} | TP:${tp} | SL:{sl} | Telegram: {'OK' if enviado else 'FALLÓ'}")


# ═════════════════════════════════════════════════════════════════
#  BUCLE PRINCIPAL
# ═════════════════════════════════════════════════════════════════
def main():
    log.info("═══════════════════════════════════════")
    log.info("  GERARDO_BOT — EMA 7/10 ARRANCANDO  ")
    log.info("═══════════════════════════════════════")

    validar_config()
    estado["modo"] = "PAPER"
    log.info(f"Modo: PAPER | {SIMBOLO} | Valor punto: ${VALOR_PUNTO} | TP: {TAKE_PROFIT_PUNTOS}pts | SL: {STOP_LOSS_PUNTOS}pts")
    log.info(f"Horario: {HORA_APERTURA} a {HORA_CIERRE} (Argentina)")
    agregar_log_dashboard("INFO", None, f"Bot arrancado · PAPER · TP:{TAKE_PROFIT_PUNTOS}pts · SL:{STOP_LOSS_PUNTOS}pts")

    # ── Comandos de Telegram (/stop /start /estado) ──
    def fn_stop():
        if estado["posicion_abierta"]:
            try:
                cerrar_posicion(obtener_precio_actual(), "STOP MANUAL")
            except Exception as e:
                log.error(f"Error cerrando posición por /stop: {e}")

    def fn_estado():
        precio = historial_ohlc[-1]["close"] if historial_ohlc else None
        return {
            "precio":      precio,
            "posicion":    estado["posicion_abierta"],
            "entrada":     estado["precio_entrada"],
            "pnl":         estado["pnl_paper"],
            "ops":         estado["operaciones_hoy"],
            "max_ops":     MAX_OPERACIONES_DIA,
            "perdida":     estado["perdida_acumulada"],
            "max_perdida": MAX_PERDIDA_DIARIA_USD,
            "buys":        estado["buys_hoy"],
            "sells":       estado["sells_hoy"],
        }

    registrar_callbacks(fn_stop, fn_estado)
    iniciar_listener()
    log.info("Listener de comandos Telegram iniciado — /ayuda para ver comandos")

    estado["telegram_ok"] = enviar_telegram(
        f"🤖 <b>Gerardo_Bot encendido — EMA 7/10</b>\n"
        f"Símbolo: {SIMBOLO} | Modo: PAPER\n"
        f"Entrada: cruce EMA7/10 confirmado en vela siguiente\n"
        f"Take profit: {TAKE_PROFIT_PUNTOS} pts | Stop loss: {STOP_LOSS_PUNTOS} pts\n"
        f"Horario: {HORA_APERTURA} a {HORA_CIERRE}"
    )

    esperando_token = actualizar_token()
    if esperando_token:
        log.warning("Token de Schwab vencido — no se carga historial hasta que te loguees.")
        historial_ohlc = []
    else:
        log.info(f"Cargando historial OHLC (velas de {VELA_SEG // 60} min)...")
        historial_ohlc = obtener_historial_ohlc(40)
    if historial_ohlc:
        log.info(f"Historial cargado: {len(historial_ohlc)} velas. Último: ${historial_ohlc[-1]['close']}")
        agregar_log_dashboard("INFO", historial_ohlc[-1]["close"], f"Historial cargado · {len(historial_ohlc)} velas")
    else:
        log.warning("Sin historial — arrancando con memoria vacía.")
        agregar_log_dashboard("WARN", None, "Sin historial — necesita 20 velas para activarse")

    # Vela en construcción (se arma con los precios realtime de Schwab)
    vela_actual    = None    # {"open","high","low","close"} de la ventana en curso
    bucket_actual  = None    # id de la cubeta actual
    resultado_live = {"ema7_actual": None, "ema10_actual": None}
    senal_live     = "ESPERANDO"
    ema7_live      = None
    ema10_live     = None

    while True:
        try:
            resetear_estado_si_nuevo_dia()

            # Token de Schwab vencido — esperar a que te loguees (se abre el login solo)
            if actualizar_token():
                esperando_token = True
                vela_actual = bucket_actual = None
                close = historial_ohlc[-1]["close"] if historial_ohlc else 0
                guardar_estado(close, {"ema7_actual": None, "ema10_actual": None}, "TOKEN_VENCIDO",
                               [v["close"] for v in historial_ohlc])
                time.sleep(5)
                continue
            if esperando_token:
                # Token recién renovado → recargar historial para no arrancar con velas viejas
                esperando_token = False
                historial_ohlc = obtener_historial_ohlc(40)
                log.info(f"Token renovado — historial recargado: {len(historial_ohlc)} velas")
                agregar_log_dashboard("INFO", None, f"Token renovado · historial recargado ({len(historial_ohlc)} velas)")

            # Pausa manual por /stop de Telegram
            if esta_pausado():
                log.info("Bot pausado por /stop — esperando /start...")
                vela_actual = bucket_actual = None
                close = historial_ohlc[-1]["close"] if historial_ohlc else 0
                guardar_estado(close, {"ema7_actual": None, "ema10_actual": None}, "PAUSADO",
                               [v["close"] for v in historial_ohlc])
                time.sleep(TIMEFRAME_SEG)
                continue

            # Fuera de horario — cerrar posición, mandar reporte una vez, y NO construir velas
            if not es_horario_operacion():
                try:
                    precio = obtener_precio_actual()
                except Exception:
                    precio = historial_ohlc[-1]["close"] if historial_ohlc else 0
                vela_actual = bucket_actual = None   # cortamos la vela en curso

                if not estado["reporte_enviado"]:
                    if estado["posicion_abierta"]:
                        cerrar_posicion(precio, "CIERRE HORARIO")
                    estado["senal_pendiente"] = None
                    enviar_reporte_diario(estado, operaciones_dia)
                    estado["reporte_enviado"] = True
                    agregar_log_dashboard("INFO", precio, f"Fuera de horario — reporte enviado · reabre {HORA_APERTURA}")

                hora = datetime.now().strftime("%H:%M:%S")
                log.info(f"[{hora}] Fuera de horario · {precio:.2f} · reabre {HORA_APERTURA}")
                guardar_estado(precio, {"ema7_actual": None, "ema10_actual": None}, "FUERA_HORARIO",
                               [v["close"] for v in historial_ohlc])
                time.sleep(TIMEFRAME_SEG)
                continue
            else:
                estado["reporte_enviado"] = False

            if circuit_breaker_activo():
                log.warning("Circuit breaker activo. Reintentando en 60s...")
                close = historial_ohlc[-1]["close"] if historial_ohlc else 0
                guardar_estado(close, {"ema7_actual": None, "ema10_actual": None}, "CIRCUIT_BREAKER",
                               [v["close"] for v in historial_ohlc])
                time.sleep(60)
                continue

            # ══ Nueva lectura de precio (Schwab, realtime) ══
            precio = obtener_precio_actual()
            bucket = int(time.time() // VELA_SEG)
            hora   = datetime.now().strftime("%H:%M:%S")
            vela_cerrada = False

            # ── Construcción de la vela ──
            if vela_actual is None:
                vela_actual   = {"open": precio, "high": precio, "low": precio, "close": precio}
                bucket_actual = bucket
            elif bucket == bucket_actual:
                # Misma vela → actualizamos OHLC con el precio nuevo
                vela_actual["high"]  = max(vela_actual["high"], precio)
                vela_actual["low"]   = min(vela_actual["low"],  precio)
                vela_actual["close"] = precio
            else:
                # Cambió la cubeta → la vela anterior CERRÓ
                historial_ohlc.append(vela_actual)
                if len(historial_ohlc) > 60:
                    historial_ohlc.pop(0)
                estado["velas_procesadas"] += 1
                vela_cerrada = True
                # Arrancamos la nueva vela con el precio actual
                vela_actual   = {"open": precio, "high": precio, "low": precio, "close": precio}
                bucket_actual = bucket

            # ── EMAs EN VIVO (para el dashboard) — incluyen la vela en construcción ──
            serie_live     = historial_ohlc + [vela_actual]
            resultado_live = calcular_emas(serie_live)
            senal_live     = resultado_live.get("señal", "ESPERANDO")
            ema7_live      = resultado_live.get("ema7_actual")
            ema10_live     = resultado_live.get("ema10_actual")

            # ── SALIDA: TP/SL se chequean en CADA tick (salida rápida, no espera cierre de vela) ──
            if estado["posicion_abierta"]:
                motivo = verificar_tp_sl(precio)
                if motivo == "TAKE":
                    cerrar_posicion(precio, "TAKE PROFIT")
                elif motivo == "STOP":
                    cerrar_posicion(precio, "STOP LOSS")

            # ── ENTRADA: las decisiones se toman SOLO cuando CIERRA una vela ──
            if vela_cerrada:
                resultado = calcular_emas(historial_ohlc)   # EMAs sobre velas YA CERRADAS
                senal     = resultado["señal"]
                ema7      = resultado.get("ema7_actual")
                ema10     = resultado.get("ema10_actual")
                adx       = resultado.get("adx")
                adx_txt   = f" | ADX:{adx}" if adx is not None else ""
                cierre    = historial_ohlc[-1]["close"]
                log.info(f"[{hora}] ▸ VELA CERRADA · close:{cierre:.2f} | EMA7:{ema7} EMA10:{ema10}{adx_txt} | señal:{senal}")

                if not estado["posicion_abierta"]:
                    if estado["senal_pendiente"] is None:
                        # Cruce nuevo en la vela que cerró → queda pendiente para confirmar en la SIGUIENTE
                        if senal in ("COMPRAR", "VENDER"):
                            estado["senal_pendiente"] = senal
                            log.info(f"[{hora}] Cruce {senal} en la vela cerrada — espero la vela siguiente para confirmar")
                            agregar_log_dashboard("WARN", precio, f"Cruce {senal} — esperando confirmación (vela siguiente)")
                    else:
                        # Ya veníamos con un cruce pendiente → esta vela que cerró es la "vela siguiente"
                        pend = estado["senal_pendiente"]
                        confirmado = False
                        if ema7 is not None and ema10 is not None:
                            if pend == "COMPRAR" and ema7 > ema10:
                                confirmado = True
                            elif pend == "VENDER" and ema7 < ema10:
                                confirmado = True
                        if confirmado:
                            log.info(f"[{hora}] Cruce {pend} CONFIRMADO en la vela siguiente — ENTRANDO")
                            abrir_posicion(pend, precio, resultado)
                        else:
                            log.info(f"[{hora}] Cruce {pend} NO confirmado en la vela siguiente — descartado")
                            agregar_log_dashboard("INFO", precio, f"Cruce {pend} no confirmado — descartado")
                        estado["senal_pendiente"] = None
                else:
                    estado["senal_pendiente"] = None

            # ── Log de monitoreo (cada tick) ──
            estado_pos = estado["posicion_abierta"] or ("PEND:" + estado["senal_pendiente"] if estado["senal_pendiente"] else "flat")
            estado_vela = "▸cierra" if vela_cerrada else "construye"
            log.info(f"[{hora}] {precio:.2f} | EMA7:{ema7_live} EMA10:{ema10_live} | {estado_pos} | vela:{estado_vela}")

            # ── Guardar estado para el dashboard: EMAs EN VIVO + precio actual ──
            historial_close = [v["close"] for v in historial_ohlc] + [vela_actual["close"]]
            guardar_estado(precio, resultado_live, senal_live, historial_close)
            time.sleep(TIMEFRAME_SEG)

        except KeyboardInterrupt:
            log.info("Bot detenido manualmente.")
            if estado["posicion_abierta"]:
                try:
                    cerrar_posicion(obtener_precio_actual(), "CIERRE MANUAL")
                except Exception:
                    pass
            enviar_reporte_diario(estado, operaciones_dia)
            agregar_log_dashboard("WARN", None, "Bot detenido manualmente")
            guardar_estado(0, {}, "DETENIDO", [])
            enviar_telegram("🛑 <b>Bot detenido manualmente.</b>")
            break

        except Exception as e:
            log.error(f"Error en el bucle: {e}", exc_info=True)
            agregar_log_dashboard("WARN", None, f"Error: {e}")
            enviar_telegram(f"⚠️ <b>Error:</b> {e}\nReintentando en 30s...")
            time.sleep(30)


if __name__ == "__main__":
    main()