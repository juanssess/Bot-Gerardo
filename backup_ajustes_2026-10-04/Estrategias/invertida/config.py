import os
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ══════════════════════════════════════════════
#  SCHWAB / THINKORSWIM
# ══════════════════════════════════════════════
SCHWAB_APP_KEY    = os.getenv("SCHWAB_APP_KEY")
SCHWAB_APP_SECRET = os.getenv("SCHWAB_APP_SECRET")

# ══════════════════════════════════════════════
#  PARÁMETROS DE TRADING
# ══════════════════════════════════════════════
SIMBOLO       = os.getenv("SIMBOLO", "/ES")
CANTIDAD      = int(os.getenv("CANTIDAD", "1"))
TIMEFRAME_SEG = 1

# Tamaño de vela en segundos — lo usan el vivo (main.py) y el historial (schwab_api.py)
VELA_SEG = 60

# ══════════════════════════════════════════════
#  VALOR POR PUNTO (tick value) — por símbolo
# ══════════════════════════════════════════════
VALOR_POR_PUNTO = {
    "/ES":  50.0,
    "/NQ":  20.0,
    "/MES": 5.0,
    "/MNQ": 2.0,
    "/CL":  1000.0,
    "/GC":  100.0,
    "/ZC":  50.0,
    "/ZS":  50.0,
    "/ZW":  50.0,
    "/ZL":  600.0,
    "/ZM":  100.0,
    "/LE":  400.0,
}

def get_valor_por_punto() -> float:
    return VALOR_POR_PUNTO.get(SIMBOLO, 50.0)

# ══════════════════════════════════════════════
#  LÍMITES DE RIESGO DIARIO  (0 = sin límite)
# ══════════════════════════════════════════════
MAX_PERDIDA_DIARIA_USD = float(os.getenv("MAX_PERDIDA_DIARIA_USD", "0"))
MAX_OPERACIONES_DIA    = int(os.getenv("MAX_OPERACIONES_DIA", "0"))

# ══════════════════════════════════════════════
#  ESTRATEGIA INVERTIDA
# ══════════════════════════════════════════════
# 1 = opera al revés del cruce: cruce alcista → VENDE (SHORT), cruce bajista → COMPRA (LONG).
# 0 = estrategia original.
INVERTIR_ESTRATEGIA = os.getenv("INVERTIR_ESTRATEGIA", "1") == "1"

# ══════════════════════════════════════════════
#  GESTIÓN DE RIESGO POR OPERACIÓN
# ══════════════════════════════════════════════
TAKE_PROFIT_PUNTOS = float(os.getenv("TAKE_PROFIT_PUNTOS", "3.5"))   # 3.5 pts = 14 ticks en /ES
STOP_LOSS_PUNTOS   = float(os.getenv("STOP_LOSS_PUNTOS", "0"))

# Comisión por contrato y por lado (entrada o salida), en USD, para el P&L paper.
# Schwab: $2.25 + cargos de exchange/regulatorios ≈ $2.62 (estimado — confirmalo en tu cuenta
# y ponelo en .env como COMISION_POR_LADO_USD=...). Una operación completa paga 2 lados.
COMISION_POR_LADO_USD = float(os.getenv("COMISION_POR_LADO_USD", "2.62"))

# Filtro ADX
ADX_MINIMO = float(os.getenv("ADX_MINIMO", "25"))

# Hora de cierre
HORA_CIERRE_MERCADO = os.getenv("HORA_CIERRE_MERCADO", "17:30")

# ══════════════════════════════════════════════
#  VALIDACIÓN
# ══════════════════════════════════════════════
def validar_config():
    errores = []
    if not TELEGRAM_TOKEN:
        errores.append("TELEGRAM_TOKEN no está definido en .env")
    if not TELEGRAM_CHAT_ID:
        errores.append("TELEGRAM_CHAT_ID no está definido en .env")

    schwab_listo = bool(SCHWAB_APP_KEY and SCHWAB_APP_SECRET)

    if errores:
        for e in errores:
            print(f"[CONFIG ERROR] {e}")
        raise EnvironmentError("Faltan variables críticas en .env.")

    return schwab_listo