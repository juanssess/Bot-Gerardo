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

ESTRATEGIA INVERTIDA (INVERTIR_ESTRATEGIA=1 en .env):
    - Cruce alcista confirmado → abre SHORT; cruce bajista confirmado → abre LONG.
    - Límites diarios: MAX_PERDIDA_DIARIA_USD / MAX_OPERACIONES_DIA en 0 = sin límite.

Modo PAPER forzado (schwab_api nunca manda órdenes reales).
"""

import time
import fcntl
import signal
import sys
import logging
from logging.handlers import RotatingFileHandler
import json
import os
from datetime import datetime, date

from config import (
    validar_config, TIMEFRAME_SEG, MAX_PERDIDA_DIARIA_USD, MAX_OPERACIONES_DIA,
    SIMBOLO, TAKE_PROFIT_PUNTOS, STOP_LOSS_PUNTOS, get_valor_por_punto, VELA_SEG,
    COMISION_POR_LADO_USD, INVERTIR_ESTRATEGIA,
)
from estrategia        import calcular_emas
from schwab_api        import obtener_precio_actual, obtener_historial_ohlc, ejecutar_orden, contrato_actual
from reporte           import enviar_reporte_diario
from telegram_bot      import enviar_telegram, iniciar_listener, registrar_callbacks, esta_pausado
from control_token     import revisar_token
from horario           import es_horario_operacion, sesion_actual, texto_proxima_apertura, horario_local
from notas             import Diario

ESTADO_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado.json")
SESION_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sesion.json")   # sobrevive a reinicios
VALOR_PUNTO = get_valor_por_punto()
COMISION_OPERACION = round(COMISION_POR_LADO_USD * 2, 2)   # entrada + salida, 1 contrato

# Si pasa más de esto sin precio (errores, la Mac se durmió…) se recarga el historial de Schwab
MAX_HUECO_SEG = 2 * VELA_SEG

# ═════════════════════════════════════════════════════════════════
#  HORARIO DE OPERACIÓN — ver horario.py (hora NY: 18:00 a 16:30, sin fines de semana)
# ═════════════════════════════════════════════════════════════════
# Fuera de horario no hace falta pedir precio cada segundo
PAUSA_FUERA_HORARIO_SEG = 10

# ═════════════════════════════════════════════════════════════════
#  LOGGING
# ═════════════════════════════════════════════════════════════════
# bot.log rota a los 10 MB y guarda 5 archivos viejos (bot.log.1 … bot.log.5) → máximo ~60 MB
_archivo_log = RotatingFileHandler(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log"),
    maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
)
_archivo_log.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%d/%m %H:%M:%S"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(), _archivo_log],
)
# Cada pedido a Schwab se logueaba ("HTTP Request: GET …"): era la mitad del log
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════
#  ESTADO DEL DÍA
# ═════════════════════════════════════════════════════════════════
estado = {
    "fecha_actual":       sesion_actual(),   # sesión del CME (la de las 18:00 NY es la del día siguiente)
    "perdida_acumulada":  0.0,
    "operaciones_hoy":    0,
    "posicion_abierta":   None,    # "LONG", "SHORT" o None
    "precio_entrada":     None,
    "t_entrada":          None,    # epoch de la entrada (para marcarla en el gráfico)
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
    "ema7_live":          None,    # EMAs en vivo (para /estado de Telegram)
    "ema10_live":         None,
    "reporte_enviado":    False,
    "token_vence":        None,    # "dd/mm HH:MM" en que vence el token de Schwab
    "token_vence_ts":     None,    # lo mismo en epoch (para la cuenta regresiva del dashboard)
    "aviso_token":        None,    # texto para el dashboard si falta poco o venció
    "token_vencido":      False,
}

operaciones_dia = []
log_dashboard   = []
diario          = None    # nota del día en la app Notas (se crea en main)


def anotar(texto: str):
    """Evento importante para la nota del día (errores, cortes, token, horario…)."""
    if diario:
        diario.evento(texto)


# ═════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════
def agregar_log_dashboard(tipo: str, precio, mensaje: str):
    hora = datetime.now().strftime("%H:%M:%S")
    log_dashboard.insert(0, {"hora": hora, "tipo": tipo, "precio": precio, "mensaje": mensaje})
    if len(log_dashboard) > 50:
        log_dashboard.pop()


def _serie_ema(closes: list, span: int) -> list:
    """Misma EMA que estrategia.py (ewm adjust=False), vela por vela."""
    k, ema, serie = 2 / (span + 1), None, []
    for c in closes:
        ema = c if ema is None else c * k + ema * (1 - k)
        serie.append(round(ema, 4))
    return serie


# Estados en los que el bot no está buscando entradas
ESTADOS_BOT = ("PAUSADO", "FUERA_HORARIO", "CIRCUIT_BREAKER", "TOKEN_VENCIDO", "DETENIDO")


def guardar_estado(precio: float, resultado_ema: dict, senal: str, velas: list):
    hora = datetime.now().strftime("%H:%M:%S")
    ema7  = resultado_ema.get("ema7_actual")
    ema10 = resultado_ema.get("ema10_actual")
    velas = [v for v in velas if v and "t" in v][-60:]
    closes = [v["close"] for v in velas]
    historial_close = closes

    pnl_abierto = None
    if estado["posicion_abierta"] and estado["precio_entrada"] is not None and precio:
        signo = 1 if estado["posicion_abierta"] == "LONG" else -1
        # Neto: lo que quedaría si cerrara ahora, ya descontada la comisión de ida y vuelta
        pnl_abierto = round((precio - estado["precio_entrada"]) * signo * VALOR_PUNTO - COMISION_OPERACION, 2)

    hora_ap, hora_ci = horario_local()
    try:
        contrato = contrato_actual()
    except Exception:
        contrato = SIMBOLO

    datos = {
        "timestamp":          hora,
        "ts":                 time.time(),
        "estado_bot":         senal if senal in ESTADOS_BOT else "OPERANDO",
        "simbolo":            SIMBOLO,
        "contrato":           contrato,
        "vela_seg":           VELA_SEG,
        "valor_punto":        VALOR_PUNTO,
        "hora_apertura":      hora_ap,
        "hora_cierre":        hora_ci,
        "reabre":             texto_proxima_apertura(),
        "sesion":             estado["fecha_actual"].isoformat(),
        "senal_pendiente":    estado["senal_pendiente"],
        "t_entrada":          estado["t_entrada"],
        "pnl_abierto":        pnl_abierto,
        "comision_operacion": COMISION_OPERACION,
        "velas": [
            {"t": v["t"], "o": v["open"], "h": v["high"], "l": v["low"], "c": v["close"]}
            for v in velas
        ],
        "ema7_serie":         _serie_ema(closes, 7),
        "ema10_serie":        _serie_ema(closes, 10),
        "operaciones":        operaciones_dia[-50:],
        "modo":               estado["modo"],
        "precio_actual":      precio,
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
        "token_vence_ts":     estado["token_vence_ts"],
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


# ═════════════════════════════════════════════════════════════════
#  SESIÓN — contadores del día y posición, guardados en sesion.json
# ═════════════════════════════════════════════════════════════════
CAMPOS_SESION = (
    "perdida_acumulada", "operaciones_hoy", "pnl_paper", "buys_hoy", "sells_hoy", "reporte_enviado",
)
CAMPOS_POSICION = (
    "posicion_abierta", "precio_entrada", "t_entrada", "stop_loss_precio", "take_profit_precio",
)


def guardar_sesion():
    """Guarda contadores, operaciones y posición abierta, para retomarlos si el bot se reinicia."""
    datos = {k: estado[k] for k in CAMPOS_SESION + CAMPOS_POSICION}
    datos["sesion"]      = estado["fecha_actual"].isoformat()
    datos["operaciones"] = operaciones_dia
    datos["log"]         = log_dashboard[:50]
    try:
        tmp = SESION_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(tmp, SESION_JSON)
    except Exception as e:
        log.warning(f"No se pudo guardar sesion.json: {e}")


def cargar_sesion():
    """
    Al arrancar retoma SOLO la posición abierta (si había), para no perderle el TP/SL.
    El P&L, las operaciones y la pérdida acumulada arrancan de cero en cada encendido:
    lo que hizo el bot en el encendido anterior quedó guardado en su nota de la app Notas.
    """
    try:
        with open(SESION_JSON, encoding="utf-8") as f:
            datos = json.load(f)
    except FileNotFoundError:
        return
    except Exception as e:
        log.warning(f"No se pudo leer sesion.json: {e}")
        return

    if datos.get("posicion_abierta"):
        for k in CAMPOS_POSICION:
            estado[k] = datos.get(k)
        msg = (f"Posición {estado['posicion_abierta']} retomada · entrada ${estado['precio_entrada']:.2f} · "
               f"TP ${estado['take_profit_precio']} · SL ${estado['stop_loss_precio']}")
        log.warning(msg)
        agregar_log_dashboard("WARN", estado["precio_entrada"], msg)
        anotar(f"{msg} (venía del encendido anterior)")
        enviar_telegram(f"♻️ <b>Bot reiniciado — {msg}</b>")


def resetear_estado_si_nueva_sesion():
    """Al abrir una sesión nueva (18:00 NY) se reinician los contadores del día."""
    sesion = sesion_actual()
    if estado["fecha_actual"] != sesion and es_horario_operacion():
        log.info(f"Nueva sesión {sesion} — reseteando contadores.")
        if diario:
            diario.cerrar_y_empezar_otra(estado, operaciones_dia, "fin de la sesión (empieza la del " f"{sesion:%d/%m})")
        estado.update({
            "fecha_actual": sesion, "perdida_acumulada": 0.0,
            "operaciones_hoy": 0, "buys_hoy": 0, "sells_hoy": 0,
            "pnl_paper": 0.0, "reporte_enviado": False,
        })
        operaciones_dia.clear()
        agregar_log_dashboard("INFO", None, f"Nueva sesión {sesion:%d/%m} — contadores reseteados")
        guardar_sesion()


def actualizar_token() -> bool:
    """Revisa el token de Schwab, actualiza el estado para el dashboard. Devuelve True si venció."""
    info = revisar_token()
    estado["token_vence"]   = datetime.fromtimestamp(info["vence"]).strftime("%d/%m %H:%M") if info["vence"] else None
    estado["token_vence_ts"] = info["vence"] or None
    estado["aviso_token"]   = info["aviso"]
    estado["token_vencido"] = info["vencido"]
    if info["evento"]:
        agregar_log_dashboard("WARN" if info["vencido"] else "INFO", None, info["evento"])
        anotar(info["evento"])
    return info["vencido"]


# ═════════════════════════════════════════════════════════════════
#  AVISOS DE ERROR — uno al empezar, recordatorio cada 30 min, uno al resolverse
# ═════════════════════════════════════════════════════════════════
RECORDATORIO_ERROR_SEG = 30 * 60
_error = {"desde": None, "ultimo_aviso": 0.0, "intentos": 0}


def _duracion(seg: float) -> str:
    m = int(seg // 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min" if m else f"{int(seg)} s"


# ═════════════════════════════════════════════════════════════════
#  APAGADO — Ctrl+C, cerrar la ventana de Terminal o apagar la Mac
# ═════════════════════════════════════════════════════════════════
MOTIVO_CTRL_C   = "lo apagaste con Ctrl+C"
_motivo_apagado = MOTIVO_CTRL_C


def _apagar_por_senal(signum, frame):
    global _motivo_apagado
    _motivo_apagado = ("se cerró la ventana de Terminal" if signum == signal.SIGHUP
                       else "se apagó o reinició la Mac (o se cerró el proceso)")
    raise KeyboardInterrupt


def apagar():
    # Que una segunda señal (ej. cerrar la ventana mientras se apaga) no corte el cierre a la mitad
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    log.info(f"Bot detenido — {_motivo_apagado}.")
    # Solo Ctrl+C cierra la posición. Si se cerró la ventana o se reinició la Mac,
    # queda guardada en sesion.json y se retoma al volver a prenderlo.
    if estado["posicion_abierta"] and _motivo_apagado == MOTIVO_CTRL_C:
        try:
            cerrar_posicion(obtener_precio_actual(), "CIERRE MANUAL")
        except Exception:
            pass
    try:
        enviar_reporte_diario(estado, operaciones_dia)
    except Exception as e:
        log.warning(f"No se pudo mandar el reporte: {e}")
    agregar_log_dashboard("WARN", None, f"Bot detenido — {_motivo_apagado}")
    guardar_estado(0, {}, "DETENIDO", [])
    enviar_telegram(f"🛑 <b>Bot detenido</b> — {_motivo_apagado}.")
    if diario:
        diario.actualizar(estado, operaciones_dia, fin=_motivo_apagado, esperar=True)
        log.info("Nota del día guardada en la app Notas (carpeta Gerardo_Bot).")


def registrar_error(e: Exception):
    ahora = time.time()
    _error["intentos"] += 1
    if _error["desde"] is None:
        _error["desde"] = _error["ultimo_aviso"] = ahora
        log.error(f"Error en el bucle: {e}", exc_info=True)
        agregar_log_dashboard("WARN", None, f"Error: {e}")
        anotar(f"Error: {e}")
        enviar_telegram(f"⚠️ <b>Error:</b> {e}\nReintento cada 30 s. Te aviso cuando se resuelva.")
        return
    log.error(f"Error en el bucle (sigue, intento {_error['intentos']}): {e}")
    if ahora - _error["ultimo_aviso"] >= RECORDATORIO_ERROR_SEG:
        _error["ultimo_aviso"] = ahora
        dur = _duracion(ahora - _error["desde"])
        agregar_log_dashboard("WARN", None, f"Error sigue hace {dur}: {e}")
        enviar_telegram(f"⚠️ <b>El error sigue hace {dur}</b> ({_error['intentos']} intentos)\n{e}")


def marcar_ok():
    """Llamar cuando una vuelta del bucle salió bien: si venía con error, avisa que se resolvió."""
    if _error["desde"] is None:
        return
    dur = _duracion(time.time() - _error["desde"])
    log.info(f"Error resuelto después de {dur} ({_error['intentos']} intentos)")
    agregar_log_dashboard("INFO", None, f"Error resuelto · duró {dur}")
    anotar(f"Error resuelto después de {dur} ({_error['intentos']} intentos)")
    enviar_telegram(f"✅ <b>Error resuelto</b> · duró {dur} ({_error['intentos']} intentos)")
    _error.update(desde=None, ultimo_aviso=0.0, intentos=0)


def texto_ops() -> str:
    """'7/50' con límite, o '7' si no hay límite de operaciones."""
    n = estado["operaciones_hoy"]
    return f"{n}/{MAX_OPERACIONES_DIA}" if MAX_OPERACIONES_DIA > 0 else f"{n} (sin límite)"


def circuit_breaker_activo() -> bool:
    """Límites diarios. Un límite en 0 está desactivado."""
    if MAX_PERDIDA_DIARIA_USD > 0 and estado["perdida_acumulada"] >= MAX_PERDIDA_DIARIA_USD:
        log.warning(f"CIRCUIT BREAKER: pérdida ${estado['perdida_acumulada']:.2f} >= ${MAX_PERDIDA_DIARIA_USD}")
        agregar_log_dashboard("WARN", None, f"Circuit breaker — pérdida ${estado['perdida_acumulada']:.2f}")
        return True
    if MAX_OPERACIONES_DIA > 0 and estado["operaciones_hoy"] >= MAX_OPERACIONES_DIA:
        log.warning(f"CIRCUIT BREAKER: {estado['operaciones_hoy']} ops >= {MAX_OPERACIONES_DIA}")
        agregar_log_dashboard("WARN", None, "Circuit breaker — máximo de operaciones alcanzado")
        return True
    return False


# ═════════════════════════════════════════════════════════════════
#  CERRAR POSICIÓN
# ═════════════════════════════════════════════════════════════════
def cerrar_posicion(precio: float, motivo: str):
    pos            = estado["posicion_abierta"]
    precio_entrada = estado["precio_entrada"]

    if pos == "LONG":
        puntos      = precio - precio_entrada
        lado_cierre = "SELL"
    else:
        puntos      = precio_entrada - precio
        lado_cierre = "BUY"
    bruto     = puntos * VALOR_PUNTO
    resultado = bruto - COMISION_OPERACION      # P&L neto (lo que quedaría con plata real)

    estado["pnl_paper"] += resultado
    if resultado < 0:
        estado["perdida_acumulada"] += abs(resultado)

    operaciones_dia.append({
        "entrada":   precio_entrada,
        "salida":    precio,
        "posicion":  pos,
        "resultado": round(resultado, 2),
        "bruto":     round(bruto, 2),
        "comision":  COMISION_OPERACION,
        "motivo":    motivo,
        "hora":      datetime.now().strftime("%H:%M:%S"),
        "puntos":    round(puntos, 2),
        "t_entrada": estado["t_entrada"],
        "t_salida":  time.time(),
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
        f"💵 Bruto:      ${bruto:+.2f} ({puntos:+.2f} pts)\n"
        f"🧾 Comisión:   -${COMISION_OPERACION:.2f}\n"
        f"💰 Neto:       ${resultado:+.2f}\n"
        f"📊 P&L día:    ${estado['pnl_paper']:+.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Operaciones hoy: {texto_ops()}"
    )

    log.info(f"[{motivo}] {pos} | Entrada: ${precio_entrada:.2f} | Salida: ${precio:.2f} | "
             f"Bruto: ${bruto:+.2f} | Comisión: ${COMISION_OPERACION:.2f} | Neto: ${resultado:+.2f}")
    ejecutar_orden(lado_cierre)

    estado.update({
        "posicion_abierta":   None,
        "precio_entrada":     None,
        "t_entrada":          None,
        "stop_loss_precio":   None,
        "take_profit_precio": None,
    })
    guardar_sesion()
    if diario:
        diario.actualizar(estado, operaciones_dia)


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
def abrir_posicion(cruce: str, precio: float, resultado_ema: dict):
    """cruce = 'COMPRAR' (alcista) o 'VENDER' (bajista). Con INVERTIR_ESTRATEGIA se opera al revés."""
    hora = datetime.now().strftime("%H:%M:%S")
    if INVERTIR_ESTRATEGIA:
        senal = "VENDER" if cruce == "COMPRAR" else "COMPRAR"
    else:
        senal = cruce
    cruce_txt = "alcista" if cruce == "COMPRAR" else "bajista"
    inv_txt   = " · INVERTIDA" if INVERTIR_ESTRATEGIA else ""
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
    estado["t_entrada"]           = time.time()
    estado["take_profit_precio"]  = tp
    estado["stop_loss_precio"]    = sl

    if senal == "COMPRAR":
        estado["buys_hoy"] += 1
        agregar_log_dashboard("COMPRA", precio, f"Cruce {cruce_txt} confirmado EMA7/10{inv_txt} · TP:${tp} · SL:${sl}")
    else:
        estado["sells_hoy"] += 1
        agregar_log_dashboard("VENTA", precio, f"Cruce {cruce_txt} confirmado EMA7/10{inv_txt} · TP:${tp} · SL:${sl}")

    emoji  = "🟢" if senal == "COMPRAR" else "🔴"
    titulo = (f"{'COMPRA' if senal == 'COMPRAR' else 'VENTA'} — Cruce {cruce_txt.capitalize()} "
              f"(confirmado){inv_txt}")
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
        f"Operaciones hoy: {texto_ops()}"
    )
    estado["telegram_ok"] = enviado
    guardar_sesion()
    log.info(f"[ENTRADA {pos}] ${precio:.2f} | TP:${tp} | SL:{sl} | Telegram: {'OK' if enviado else 'FALLÓ'}")


# ═════════════════════════════════════════════════════════════════
#  BUCLE PRINCIPAL
# ═════════════════════════════════════════════════════════════════
_lock = None


def tomar_lock():
    """Evita que corran dos bots a la vez (duplicaría operaciones, Telegrams y archivos)."""
    global _lock
    _lock = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.lock"), "w")
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("\n❌ Ya hay un Gerardo_Bot corriendo en esta Mac. No se arranca otro.")
        print("   Si querés reiniciarlo, cerrá primero el que está corriendo (Ctrl+C en su ventana).\n")
        sys.exit(1)
    _lock.write(str(os.getpid()))
    _lock.flush()


def main():
    tomar_lock()
    log.info("═══════════════════════════════════════")
    log.info("  GERARDO_BOT — EMA 7/10 ARRANCANDO  ")
    log.info("═══════════════════════════════════════")

    validar_config()
    estado["modo"] = "PAPER"
    log.info(f"Modo: PAPER | {SIMBOLO} | Valor punto: ${VALOR_PUNTO} | TP: {TAKE_PROFIT_PUNTOS}pts | SL: {STOP_LOSS_PUNTOS}pts")
    hora_ap, hora_ci = horario_local()
    log.info(f"Horario: {hora_ap} a {hora_ci} hora local (18:00 a 16:30 NY, sin fines de semana)")

    global diario
    diario = Diario(contrato_actual(), {
        "tp_pts": TAKE_PROFIT_PUNTOS, "sl_pts": STOP_LOSS_PUNTOS, "valor_punto": VALOR_PUNTO,
        "comision": COMISION_OPERACION, "max_perdida": MAX_PERDIDA_DIARIA_USD, "vela_min": VELA_SEG // 60,
    })
    cargar_sesion()
    guardar_sesion()          # sesion.json con los contadores en cero de este encendido
    diario.actualizar(estado, operaciones_dia)   # crea la nota del día en Notas

    # Cerrar la ventana de Terminal (SIGHUP) o apagar la Mac (SIGTERM) → apagado ordenado, como Ctrl+C
    signal.signal(signal.SIGTERM, _apagar_por_senal)
    signal.signal(signal.SIGHUP, _apagar_por_senal)
    agregar_log_dashboard("INFO", None, f"Bot arrancado · PAPER · TP:{TAKE_PROFIT_PUNTOS}pts · SL:{STOP_LOSS_PUNTOS}pts"
                                        f"{' · INVERTIDA' if INVERTIR_ESTRATEGIA else ''}")

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
            "ema7":        round(estado["ema7_live"], 2)  if estado["ema7_live"]  is not None else None,
            "ema10":       round(estado["ema10_live"], 2) if estado["ema10_live"] is not None else None,
        }

    registrar_callbacks(fn_stop, fn_estado)
    iniciar_listener()

    estado["telegram_ok"] = enviar_telegram(
        f"🤖 <b>Gerardo_Bot encendido — EMA 7/10</b>\n"
        f"Símbolo: {SIMBOLO} | Modo: PAPER\n"
        f"Entrada: cruce EMA7/10 confirmado en vela siguiente"
        f"{' · INVERTIDA (cruce alcista → vende, bajista → compra)' if INVERTIR_ESTRATEGIA else ''}\n"
        f"Límites diarios: {'desactivados' if MAX_PERDIDA_DIARIA_USD <= 0 and MAX_OPERACIONES_DIA <= 0 else 'activos'}\n"
        f"Take profit: {TAKE_PROFIT_PUNTOS} pts | Stop loss: {STOP_LOSS_PUNTOS} pts\n"
        f"Horario: {hora_ap} a {hora_ci} (lun–vie, sigue al CME)"
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
    ultimo_tick    = None    # epoch del último precio leído bien (para detectar cortes)
    bucket_actual  = None    # id de la cubeta actual
    resultado_live = {"ema7_actual": None, "ema10_actual": None}
    senal_live     = "ESPERANDO"
    ema7_live      = None
    ema10_live     = None

    while True:
        try:
            resetear_estado_si_nueva_sesion()

            # Token de Schwab vencido — esperar a que te loguees (se abre el login solo)
            if actualizar_token():
                esperando_token = True
                vela_actual = bucket_actual = ultimo_tick = None
                close = historial_ohlc[-1]["close"] if historial_ohlc else 0
                guardar_estado(close, {"ema7_actual": None, "ema10_actual": None}, "TOKEN_VENCIDO",
                               historial_ohlc)
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
                if not estado.get("pausa_anotada"):
                    estado["pausa_anotada"] = True
                    anotar("Pausado por /stop de Telegram")
                vela_actual = bucket_actual = ultimo_tick = None
                close = historial_ohlc[-1]["close"] if historial_ohlc else 0
                guardar_estado(close, {"ema7_actual": None, "ema10_actual": None}, "PAUSADO",
                               historial_ohlc)
                time.sleep(TIMEFRAME_SEG)
                continue

            # Fuera de horario — cerrar posición, mandar reporte una vez, y NO construir velas
            if not es_horario_operacion():
                try:
                    precio = obtener_precio_actual()
                except Exception:
                    precio = historial_ohlc[-1]["close"] if historial_ohlc else 0
                vela_actual = bucket_actual = ultimo_tick = None   # cortamos la vela en curso

                if not estado["reporte_enviado"]:
                    if estado["posicion_abierta"]:
                        cerrar_posicion(precio, "CIERRE HORARIO")
                    estado["senal_pendiente"] = None
                    enviar_reporte_diario(estado, operaciones_dia)
                    estado["reporte_enviado"] = True
                    guardar_sesion()
                    anotar(f"Cierre de horario — reporte enviado por Telegram (reabre {texto_proxima_apertura()})")
                    diario.actualizar(estado, operaciones_dia)
                    agregar_log_dashboard("INFO", precio, f"Fuera de horario — reporte enviado · reabre {texto_proxima_apertura()}")

                hora = datetime.now().strftime("%H:%M:%S")
                log.info(f"[{hora}] Fuera de horario · {precio:.2f} · reabre {texto_proxima_apertura()}")
                guardar_estado(precio, {"ema7_actual": None, "ema10_actual": None}, "FUERA_HORARIO",
                               historial_ohlc)
                time.sleep(PAUSA_FUERA_HORARIO_SEG)
                continue

            if circuit_breaker_activo():
                log.warning("Circuit breaker activo. Reintentando en 60s...")
                if not estado.get("cb_anotado"):
                    estado["cb_anotado"] = True
                    anotar(f"Circuit breaker: se alcanzó el tope del día (pérdida ${estado['perdida_acumulada']:.2f}, "
                           f"{estado['operaciones_hoy']} ops) — no abre más operaciones")
                ultimo_tick = None
                close = historial_ohlc[-1]["close"] if historial_ohlc else 0
                guardar_estado(close, {"ema7_actual": None, "ema10_actual": None}, "CIRCUIT_BREAKER",
                               historial_ohlc)
                time.sleep(60)
                continue

            # ══ Nueva lectura de precio (Schwab, realtime) ══
            precio = obtener_precio_actual()
            marcar_ok()
            estado["pausa_anotada"] = False
            diario.precio(precio)
            diario.quizas_actualizar(estado, operaciones_dia)

            # ── Corte inesperado (errores de Schwab, la Mac se durmió…) → recargar historial ──
            # Sin esto, la vela de antes del corte se pegaría con la de ahora como si fueran seguidas.
            ahora_ts = time.time()
            if ultimo_tick is not None and ahora_ts - ultimo_tick > MAX_HUECO_SEG:
                hueco = ahora_ts - ultimo_tick
                nuevo = obtener_historial_ohlc(40)
                if nuevo:
                    historial_ohlc = nuevo
                    vela_actual = bucket_actual = None
                    estado["senal_pendiente"] = None   # el cruce pendiente era sobre velas viejas
                    msg = f"Corte de {int(hueco // 60)} min {int(hueco % 60)} s sin precio — historial recargado ({len(nuevo)} velas)"
                    log.warning(msg)
                    agregar_log_dashboard("WARN", precio, msg)
                    anotar(msg)
                else:
                    log.warning(f"Corte de {int(hueco)} s sin precio — Schwab no devolvió historial actualizado, sigo con el que tenía")
            ultimo_tick = ahora_ts
            bucket = int(time.time() // VELA_SEG)
            hora   = datetime.now().strftime("%H:%M:%S")
            vela_cerrada = False

            # ── Construcción de la vela ──
            if vela_actual is None:
                vela_actual   = {"t": bucket * VELA_SEG, "open": precio, "high": precio, "low": precio, "close": precio}
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
                vela_actual   = {"t": bucket * VELA_SEG, "open": precio, "high": precio, "low": precio, "close": precio}
                bucket_actual = bucket

            # ── EMAs EN VIVO (para el dashboard) — incluyen la vela en construcción ──
            serie_live     = historial_ohlc + [vela_actual]
            resultado_live = calcular_emas(serie_live)
            senal_live     = resultado_live.get("señal", "ESPERANDO")
            ema7_live      = resultado_live.get("ema7_actual")
            ema10_live     = resultado_live.get("ema10_actual")
            estado["ema7_live"], estado["ema10_live"] = ema7_live, ema10_live

            # ── SALIDA: TP/SL se chequean en CADA tick (salida rápida, no espera cierre de vela) ──
            if estado["posicion_abierta"]:
                motivo = verificar_tp_sl(precio)
                if motivo == "TAKE":
                    # Orden límite: se llena en el precio del TP, no en el tick (que puede ser mejor)
                    cerrar_posicion(estado["take_profit_precio"], "TAKE PROFIT")
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
                            diario.cruce("detectados")
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
                            diario.cruce("confirmados")
                            abrir_posicion(pend, precio, resultado)
                        else:
                            log.info(f"[{hora}] Cruce {pend} NO confirmado en la vela siguiente — descartado")
                            diario.cruce("descartados")
                            agregar_log_dashboard("INFO", precio, f"Cruce {pend} no confirmado — descartado")
                        estado["senal_pendiente"] = None
                else:
                    estado["senal_pendiente"] = None

            # ── Log de monitoreo (cada tick) ──
            estado_pos = estado["posicion_abierta"] or ("PEND:" + estado["senal_pendiente"] if estado["senal_pendiente"] else "flat")
            estado_vela = "▸cierra" if vela_cerrada else "construye"
            log.info(f"[{hora}] {precio:.2f} | EMA7:{ema7_live} EMA10:{ema10_live} | {estado_pos} | vela:{estado_vela}")

            # ── Guardar estado para el dashboard: EMAs EN VIVO + precio actual ──
            guardar_estado(precio, resultado_live, senal_live, historial_ohlc + [vela_actual])
            time.sleep(TIMEFRAME_SEG)

        except KeyboardInterrupt:
            break

        except Exception as e:
            registrar_error(e)
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                break

    apagar()


if __name__ == "__main__":
    main()