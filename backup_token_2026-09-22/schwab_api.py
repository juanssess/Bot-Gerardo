"""
Módulo de conexión con Schwab API.
- Precio actual:  Schwab (realtime, get_quotes)
- Historial OHLC: Schwab (velas de 1 min agrupadas de a VELA_SEG) — mismo instrumento que el vivo
- Órdenes:        PAPER simulado
"""

import os
import time
import logging
from datetime import date, timedelta
from config import SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SIMBOLO, CANTIDAD, VELA_SEG

log = logging.getLogger(__name__)

# Futuros de índices: contrato trimestral (H=mar, M=jun, U=sep, Z=dic), se elige solo.
_TRIMESTRALES = {"/ES", "/NQ", "/MES", "/MNQ"}
_MESES_TRIMESTRE = {3: "H", 6: "M", 9: "U", 12: "Z"}
# Días antes del vencimiento (3er viernes) en que se pasa al contrato siguiente (roll de CME)
_DIAS_ROLL = 8

# Otros símbolos — contrato fijo, hay que actualizarlo a mano cuando vence
_SIMBOLO_SCHWAB = {
    "/ZC":  "/ZCN26",
    "/ZS":  "/ZSN26",
    "/ZW":  "/ZWN26",
    "/GC":  "/GCQ26",
    "/CL":  "/CLN26",
}

# Tamaño de cubeta en milisegundos (mismo que las velas del vivo)
_BUCKET_MS = VELA_SEG * 1000

# Si la última vela del historial es más vieja que esto, se descarta el historial
_MAX_ATRASO_HISTORIAL_SEG = 10 * 60


def _tercer_viernes(anio: int, mes: int) -> date:
    d = date(anio, mes, 1)
    primer_viernes = d + timedelta(days=(4 - d.weekday()) % 7)
    return primer_viernes + timedelta(days=14)


def _contrato_trimestral(raiz: str, hoy: date = None) -> str:
    """Devuelve el contrato vigente, ej. /MES → /MESZ26. Pasa al siguiente en la fecha de roll."""
    hoy = hoy or date.today()
    anio = hoy.year
    for mes in (3, 6, 9, 12, 15):
        a, m = (anio + 1, 3) if mes == 15 else (anio, mes)
        if hoy < _tercer_viernes(a, m) - timedelta(days=_DIAS_ROLL):
            return f"{raiz}{_MESES_TRIMESTRE[m]}{a % 100:02d}"


def _simbolo_schwab() -> str:
    if SIMBOLO in _TRIMESTRALES:
        return _contrato_trimestral(SIMBOLO)
    return _SIMBOLO_SCHWAB.get(SIMBOLO, SIMBOLO)


# ══════════════════════════════════════════════
#  CLIENTE SCHWAB
# ══════════════════════════════════════════════
_client = None
TOKEN_PATH = "token.json"

def _get_schwab_client():
    global _client
    if _client is not None:
        return _client
    if not SCHWAB_APP_KEY or not SCHWAB_APP_SECRET:
        return None
    if not os.path.exists(TOKEN_PATH):
        print(f"[SCHWAB] No hay token.json — corré autenticar_schwab.py primero")
        return None
    try:
        import schwab
        _client = schwab.auth.client_from_token_file(
            api_key    = SCHWAB_APP_KEY,
            app_secret = SCHWAB_APP_SECRET,
            token_path = TOKEN_PATH,
        )
        return _client
    except Exception as e:
        print(f"[SCHWAB] Error cargando cliente: {e}")
        return None


# ══════════════════════════════════════════════
#  OBTENER PRECIO — Schwab realtime
# ══════════════════════════════════════════════
def obtener_precio_actual() -> float:
    client = _get_schwab_client()
    if not client:
        raise ValueError("Schwab no configurado. Verificá token.json y credenciales.")

    simbolo = _simbolo_schwab()
    try:
        # get_quotes (plural) soporta símbolos de futuros con "/" — get_quote (singular) NO
        resp = client.get_quotes([simbolo])
        data = resp.json()
        if simbolo in data:
            quote = data[simbolo].get("quote", {})
            precio = quote.get("lastPrice") or quote.get("mark")
            if precio:
                return round(float(precio), 2)
        raise ValueError(f"Schwab no devolvió precio para {simbolo}. Respuesta: {data}")
    except Exception as e:
        raise ValueError(f"Error obteniendo precio de Schwab: {e}")


# ══════════════════════════════════════════════
#  HISTORIAL OHLC — Schwab (velas de 1 min → agrupadas de a VELA_SEG)
# ══════════════════════════════════════════════
def obtener_historial_ohlc(cantidad_velas: int = 40) -> list[dict]:
    """
    Trae el historial de velas de VELA_SEG desde Schwab, mismo instrumento
    que el precio en vivo. Pide velas de 1 min y las agrupa en cubetas de VELA_SEG
    (igual que el bucketing del bot). Descarta la última cubeta porque es la vela
    en formación (todavía no cerró). Si el historial está atrasado devuelve [],
    así no se pega una vela vieja con el precio en vivo.
    """
    client = _get_schwab_client()
    if not client:
        raise ValueError("Schwab no configurado. Verificá token.json y credenciales.")

    simbolo = _simbolo_schwab()
    try:
        resp = client.get_price_history_every_minute(simbolo)
        data = resp.json()
    except Exception as e:
        raise ValueError(f"Error pidiendo historial a Schwab: {e}")

    velas_1m = data.get("candles", [])
    if not velas_1m:
        return []

    # Si la última vela de 1 min es vieja, el historial no empalma con el vivo
    atraso_seg = time.time() - int(velas_1m[-1]["datetime"]) / 1000
    if atraso_seg > _MAX_ATRASO_HISTORIAL_SEG:
        log.warning(f"Historial de {simbolo} atrasado {atraso_seg / 60:.0f} min — se descarta")
        return []

    # Agrupar velas de 1 min en cubetas de VELA_SEG (bucket = datetime_ms // _BUCKET_MS)
    buckets = {}
    orden   = []
    for c in velas_1m:
        try:
            b = int(c["datetime"]) // _BUCKET_MS
        except (KeyError, TypeError, ValueError):
            continue
        if b not in buckets:
            buckets[b] = {"open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            orden.append(b)
        else:
            buckets[b]["high"]  = max(buckets[b]["high"], c["high"])
            buckets[b]["low"]   = min(buckets[b]["low"],  c["low"])
            buckets[b]["close"] = c["close"]

    velas = [
        {
            "open":  round(float(buckets[b]["open"]),  4),
            "high":  round(float(buckets[b]["high"]),  4),
            "low":   round(float(buckets[b]["low"]),   4),
            "close": round(float(buckets[b]["close"]), 4),
        }
        for b in orden
    ]

    # Descartar la última cubeta: es la vela en formación (no cerró)
    if len(velas) > 1:
        velas = velas[:-1]

    return velas[-cantidad_velas:]


def obtener_historial_precios(cantidad_velas: int = 40) -> list[float]:
    ohlc = obtener_historial_ohlc(cantidad_velas)
    return [v["close"] for v in ohlc]


# ══════════════════════════════════════════════
#  EJECUTAR ORDEN — PAPER FORZADO
# ══════════════════════════════════════════════
def ejecutar_orden(lado: str, cantidad: int = CANTIDAD) -> dict:
    precio = obtener_precio_actual()
    print(f"[PAPER TRADING] Orden simulada: {lado} {cantidad}x {SIMBOLO} @ {precio}")
    return {
        "estado":   "PAPER",
        "lado":     lado,
        "simbolo":  SIMBOLO,
        "cantidad": cantidad,
        "precio":   precio,
    }