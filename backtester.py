"""
Backtester para Gerardo_Bot — cruce de EMAs (ver config.py) en /ES
===============================================
Descarga 1 año de datos históricos de yfinance y simula
la estrategia completa con la misma lógica del bot real.

Uso:
    python backtester.py

Manda el reporte completo por Telegram al terminar.
"""

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from telegram_bot import enviar_telegram
from config import SIMBOLO, TAKE_PROFIT_PUNTOS, INVERTIR_ESTRATEGIA, EMA_RAPIDA, EMA_LENTA, EMA_TXT

# ══════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════
SIMBOLO_YF = {
    "/ES": "ES=F", "/NQ": "NQ=F", "/CL": "CL=F",
    "/GC": "GC=F", "/MES": "MES=F", "/MNQ": "MNQ=F",
}.get(SIMBOLO, "ES=F")

PUNTO_VALOR  = 50   # $50 por punto en /ES con 1 contrato
COMISION     = 2.50 # comisión por lado (ida + vuelta = $5 por trade)

# Horario de operación (hora local del mercado — ET)
HORA_INICIO = "09:30"
HORA_FIN    = "16:00"


# ══════════════════════════════════════════════
#  DESCARGAR DATOS
# ══════════════════════════════════════════════
def descargar_datos() -> pd.DataFrame:
    print(f"Descargando 1 año de datos de {SIMBOLO_YF}...")
    fin   = datetime.now()
    inicio = fin - timedelta(days=365)

    df = yf.download(
        SIMBOLO_YF,
        start    = inicio.strftime("%Y-%m-%d"),
        end      = fin.strftime("%Y-%m-%d"),
        interval = "1h",
        progress = False,
    )

    if df.empty:
        raise ValueError(f"No se pudieron descargar datos para {SIMBOLO_YF}")

    df = df[["Close"]].copy()
    df.columns = ["precio"]
    df.index   = pd.to_datetime(df.index)

    # Filtrar solo horario de mercado regular
    df = df.between_time(HORA_INICIO, HORA_FIN)
    df = df.dropna()

    print(f"Datos descargados: {len(df)} velas de 1 hora")
    print(f"Período: {df.index[0].date()} → {df.index[-1].date()}")
    return df


# ══════════════════════════════════════════════
#  CALCULAR EMAs
# ══════════════════════════════════════════════
def calcular_emas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema7"]  = df["precio"].ewm(span=EMA_RAPIDA, adjust=False).mean()
    df["ema10"] = df["precio"].ewm(span=EMA_LENTA,  adjust=False).mean()
    df["ema7_prev"]  = df["ema7"].shift(1)
    df["ema10_prev"] = df["ema10"].shift(1)

    # Detectar cruces
    df["cruce_alcista"] = (df["ema7_prev"] <= df["ema10_prev"]) & (df["ema7"] > df["ema10"])
    df["cruce_bajista"] = (df["ema7_prev"] >= df["ema10_prev"]) & (df["ema7"] < df["ema10"])

    return df.dropna()


# ══════════════════════════════════════════════
#  SIMULACIÓN
# ══════════════════════════════════════════════
def simular(df: pd.DataFrame) -> dict:
    print("Simulando estrategia" + (" INVERTIDA..." if INVERTIR_ESTRATEGIA else "..."))

    # Estrategia invertida: cruce alcista → SHORT, cruce bajista → LONG.
    # Se intercambian las dos columnas y el resto de la simulación queda igual.
    if INVERTIR_ESTRATEGIA:
        df = df.rename(columns={"cruce_alcista": "cruce_bajista", "cruce_bajista": "cruce_alcista"})

    operaciones  = []
    posicion     = None   # "LONG" o "SHORT"
    precio_entrada = None
    tp_precio    = None
    dia_actual   = None
    primer_cruce_dia = False

    for i in range(1, len(df)):
        fila      = df.iloc[i]
        precio    = float(fila["precio"])
        hora      = fila.name
        dia       = hora.date()

        # Reset al inicio de cada día
        if dia != dia_actual:
            dia_actual       = dia
            primer_cruce_dia = False

            # Cerrar posición abierta del día anterior
            if posicion:
                resultado = (precio - precio_entrada) * PUNTO_VALOR if posicion == "LONG" \
                            else (precio_entrada - precio) * PUNTO_VALOR
                operaciones.append({
                    "entrada":  precio_entrada,
                    "salida":   precio,
                    "posicion": posicion,
                    "resultado": round(resultado - COMISION * 2, 2),
                    "motivo":   "CIERRE DÍA",
                    "hora":     hora,
                })
                posicion = None

        # ── Si hay posición abierta ──
        if posicion:
            # Verificar take profit
            if posicion == "LONG" and precio >= tp_precio:
                resultado = (precio - precio_entrada) * PUNTO_VALOR
                operaciones.append({
                    "entrada":   precio_entrada,
                    "salida":    precio,
                    "posicion":  posicion,
                    "resultado": round(resultado - COMISION * 2, 2),
                    "motivo":    "TAKE PROFIT",
                    "hora":      hora,
                })
                posicion = None

            elif posicion == "SHORT" and precio <= tp_precio:
                resultado = (precio_entrada - precio) * PUNTO_VALOR
                operaciones.append({
                    "entrada":   precio_entrada,
                    "salida":    precio,
                    "posicion":  posicion,
                    "resultado": round(resultado - COMISION * 2, 2),
                    "motivo":    "TAKE PROFIT",
                    "hora":      hora,
                })
                posicion = None

            # Verificar cruce contrario → cerrar y abrir en dirección opuesta
            elif posicion == "LONG" and fila["cruce_bajista"]:
                resultado = (precio - precio_entrada) * PUNTO_VALOR
                operaciones.append({
                    "entrada":   precio_entrada,
                    "salida":    precio,
                    "posicion":  posicion,
                    "resultado": round(resultado - COMISION * 2, 2),
                    "motivo":    "CRUCE CONTRARIO",
                    "hora":      hora,
                })
                # Abrir SHORT en el mismo precio
                posicion       = "SHORT"
                precio_entrada = precio
                tp_precio      = round(precio - TAKE_PROFIT_PUNTOS, 2)

            elif posicion == "SHORT" and fila["cruce_alcista"]:
                resultado = (precio_entrada - precio) * PUNTO_VALOR
                operaciones.append({
                    "entrada":   precio_entrada,
                    "salida":    precio,
                    "posicion":  posicion,
                    "resultado": round(resultado - COMISION * 2, 2),
                    "motivo":    "CRUCE CONTRARIO",
                    "hora":      hora,
                })
                # Abrir LONG en el mismo precio
                posicion       = "LONG"
                precio_entrada = precio
                tp_precio      = round(precio + TAKE_PROFIT_PUNTOS, 2)

        # ── Sin posición → esperar primer cruce del día ──
        else:
            if not primer_cruce_dia:
                if fila["cruce_alcista"]:
                    posicion         = "LONG"
                    precio_entrada   = precio
                    tp_precio        = round(precio + TAKE_PROFIT_PUNTOS, 2)
                    primer_cruce_dia = True
                elif fila["cruce_bajista"]:
                    posicion         = "SHORT"
                    precio_entrada   = precio
                    tp_precio        = round(precio - TAKE_PROFIT_PUNTOS, 2)
                    primer_cruce_dia = True
            else:
                # Ya hubo primer cruce — entrar en cualquier cruce siguiente
                if fila["cruce_alcista"]:
                    posicion       = "LONG"
                    precio_entrada = precio
                    tp_precio      = round(precio + TAKE_PROFIT_PUNTOS, 2)
                elif fila["cruce_bajista"]:
                    posicion       = "SHORT"
                    precio_entrada = precio
                    tp_precio      = round(precio - TAKE_PROFIT_PUNTOS, 2)

    return operaciones


# ══════════════════════════════════════════════
#  ANÁLISIS DE RESULTADOS
# ══════════════════════════════════════════════
def analizar(operaciones: list) -> dict:
    if not operaciones:
        return {}

    df_ops = pd.DataFrame(operaciones)
    total  = len(df_ops)

    ganadores  = df_ops[df_ops["resultado"] > 0]
    perdedores = df_ops[df_ops["resultado"] <= 0]

    pnl_total      = round(df_ops["resultado"].sum(), 2)
    tasa_aciertos  = round(len(ganadores) / total * 100, 1)
    ganancia_media = round(ganadores["resultado"].mean(), 2) if len(ganadores) > 0 else 0
    perdida_media  = round(perdedores["resultado"].mean(), 2) if len(perdedores) > 0 else 0
    mejor_trade    = round(df_ops["resultado"].max(), 2)
    peor_trade     = round(df_ops["resultado"].min(), 2)

    # P&L acumulado por mes
    df_ops["mes"] = pd.to_datetime(df_ops["hora"]).dt.to_period("M")
    por_mes = df_ops.groupby("mes")["resultado"].sum().round(2)

    # Racha máxima de pérdidas consecutivas
    racha_actual = 0
    racha_max    = 0
    for r in df_ops["resultado"]:
        if r < 0:
            racha_actual += 1
            racha_max = max(racha_max, racha_actual)
        else:
            racha_actual = 0

    # Por motivo de cierre
    por_motivo = df_ops.groupby("motivo")["resultado"].agg(["count", "sum", "mean"]).round(2)

    return {
        "total":           total,
        "ganadores":       len(ganadores),
        "perdedores":      len(perdedores),
        "pnl_total":       pnl_total,
        "tasa_aciertos":   tasa_aciertos,
        "ganancia_media":  ganancia_media,
        "perdida_media":   perdida_media,
        "mejor_trade":     mejor_trade,
        "peor_trade":      peor_trade,
        "racha_max":       racha_max,
        "por_mes":         por_mes,
        "por_motivo":      por_motivo,
    }


# ══════════════════════════════════════════════
#  REPORTE A TELEGRAM
# ══════════════════════════════════════════════
def enviar_reporte_backtest(stats: dict):
    if not stats:
        enviar_telegram("❌ Backtester: no se encontraron operaciones.")
        return

    pnl     = stats["pnl_total"]
    emoji   = "🟢" if pnl > 0 else "🔴"

    # Resumen por mes
    meses_txt = ""
    for mes, val in stats["por_mes"].items():
        em = "✅" if val > 0 else "❌"
        meses_txt += f"  {em} {mes}: ${val:+.0f}\n"

    # Resumen por motivo
    motivo_txt = ""
    for motivo, row in stats["por_motivo"].iterrows():
        motivo_txt += f"  • {motivo}: {int(row['count'])} ops · ${row['sum']:+.0f}\n"

    mensaje = (
        f"{emoji} <b>BACKTEST — {EMA_TXT} · /ES · 1 AÑO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>P&L Total:        ${pnl:+,.2f}</b>\n"
        f"📊 Operaciones:      {stats['total']}\n"
        f"✅ Ganadores:        {stats['ganadores']} ({stats['tasa_aciertos']}%)\n"
        f"❌ Perdedores:       {stats['perdedores']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Ganancia media:   ${stats['ganancia_media']:+.2f}\n"
        f"📉 Pérdida media:    ${stats['perdida_media']:+.2f}\n"
        f"🏆 Mejor trade:      ${stats['mejor_trade']:+.2f}\n"
        f"💀 Peor trade:       ${stats['peor_trade']:+.2f}\n"
        f"🔴 Racha max pérd.:  {stats['racha_max']} seguidas\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>P&L por mes:</b>\n"
        f"{meses_txt}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Por motivo de cierre:</b>\n"
        f"{motivo_txt}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"TP configurado: {TAKE_PROFIT_PUNTOS} pts · ${TAKE_PROFIT_PUNTOS * PUNTO_VALOR:.0f} por trade\n"
        f"Horario: {HORA_INICIO} - {HORA_FIN} ET\n"
        f"Estrategia: {'INVERTIDA (cruce alcista → vende, bajista → compra)' if INVERTIR_ESTRATEGIA else 'original'}"
    )

    # Telegram tiene límite de 4096 caracteres — dividir si es necesario
    if len(mensaje) > 4000:
        enviar_telegram(mensaje[:4000])
        enviar_telegram(mensaje[4000:])
    else:
        enviar_telegram(mensaje)

    print("Reporte enviado a Telegram.")


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 50)
    print(f"  BACKTESTER — GERARDO_BOT {EMA_TXT}" + (" (INVERTIDA)" if INVERTIR_ESTRATEGIA else ""))
    print("=" * 50)

    enviar_telegram("⏳ <b>Backtester iniciado</b> — descargando 1 año de datos del /ES...")

    try:
        df          = descargar_datos()
        df          = calcular_emas(df)
        operaciones = simular(df)
        stats       = analizar(operaciones)

        print(f"\nResultados:")
        print(f"  Total operaciones: {stats.get('total', 0)}")
        print(f"  P&L total: ${stats.get('pnl_total', 0):+,.2f}")
        print(f"  Tasa de aciertos: {stats.get('tasa_aciertos', 0)}%")

        enviar_reporte_backtest(stats)

    except Exception as e:
        print(f"Error: {e}")
        enviar_telegram(f"❌ <b>Error en backtester:</b> {e}")