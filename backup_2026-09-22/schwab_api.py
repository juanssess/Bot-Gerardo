"""
Módulo de conexión con Schwab API.
- Precio actual:  Schwab (realtime, get_quotes)
- Historial OHLC: Schwab (velas de 1 min agrupadas de a 3 min) — mismo instrumento que el vivo
- Órdenes:        PAPER simulado
"""

import os
from config import SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SIMBOLO, CANTIDAD

# Símbolos Schwab — contratos activos (U26 = septiembre 2026)
_SIMBOLO_SCHWAB = {
    "/ES":  "/ESU26",
    "/NQ":  "/NQU26",
    "/MES": "/MESU26",
    "/MNQ": "/MNQU26",
    "/ZC":  "/ZCN26",
    "/ZS":  "/ZSN26",
    "/ZW":  "/ZWN26",
    "/GC":  "/GCQ26",
    "/CL":  "/CLN26",
}

# Tamaño de cubeta = 3 minutos, en milisegundos (debe coincidir con VELA_SEG del main.py)
_BUCKET_MS = 180_000


def _simbolo_schwab() -> str:
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
#  HISTORIAL OHLC — Schwab (velas de 1 min → agrupadas de a 3 min)
# ══════════════════════════════════════════════
def obtener_historial_ohlc(cantidad_velas: int = 40) -> list[dict]:
    """
    Trae el historial de velas de 3 minutos desde Schwab, mismo instrumento
    que el precio en vivo. Pide velas de 1 min y las agrupa en cubetas de 3 min
    alineadas a 180 s (igual que el bucketing del bot). Descarta la última cubeta
    porque es la vela en formación (todavía no cerró).
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

    # Agrupar velas de 1 min en cubetas de 3 min (bucket = datetime_ms // 180000)
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

    velas_2m = [
        {
            "open":  round(float(buckets[b]["open"]),  4),
            "high":  round(float(buckets[b]["high"]),  4),
            "low":   round(float(buckets[b]["low"]),   4),
            "close": round(float(buckets[b]["close"]), 4),
        }
        for b in orden
    ]

    # Descartar la última cubeta: es la vela en formación (no cerró)
    if len(velas_2m) > 1:
        velas_2m = velas_2m[:-1]

    return velas_2m[-cantidad_velas:]


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