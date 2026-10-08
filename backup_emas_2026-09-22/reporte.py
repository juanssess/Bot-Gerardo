"""
Módulo de reporte diario.
Genera un resumen completo del día y lo manda por Telegram.
Se llama automáticamente desde main.py al detectar el cierre del mercado.
"""

from datetime import datetime
from notificaciones import enviar_telegram
from config import SIMBOLO, MAX_PERDIDA_DIARIA_USD, MAX_OPERACIONES_DIA


def generar_reporte_diario(estado: dict, operaciones: list) -> str:
    """
    Arma el texto del reporte diario con todas las estadísticas.
    
    estado: dict con el estado del día (pnl, operaciones, etc.)
    operaciones: lista de dicts con cada trade ejecutado
    """
    fecha = datetime.now().strftime("%d/%m/%Y")
    hora  = datetime.now().strftime("%H:%M")

    total_ops   = estado.get("operaciones_hoy", 0)
    buys        = estado.get("buys_hoy", 0)
    sells       = estado.get("sells_hoy", 0)
    pnl         = estado.get("pnl_paper", 0.0)
    perdida     = estado.get("perdida_acumulada", 0.0)
    velas       = estado.get("velas_procesadas", 0)

    # Calcular tasa de aciertos
    trades_cerrados = [op for op in operaciones if op.get("resultado") is not None]
    ganadores = [op for op in trades_cerrados if op.get("resultado", 0) > 0]
    perdedores = [op for op in trades_cerrados if op.get("resultado", 0) <= 0]
    tasa = (len(ganadores) / len(trades_cerrados) * 100) if trades_cerrados else 0

    # Mejor y peor trade
    resultados = [op.get("resultado", 0) for op in trades_cerrados]
    mejor_trade = max(resultados) if resultados else 0
    peor_trade  = min(resultados) if resultados else 0

    # Emoji de resultado general
    if pnl > 0:
        emoji_resultado = "🟢"
        titulo = "DÍA POSITIVO"
    elif pnl < 0:
        emoji_resultado = "🔴"
        titulo = "DÍA NEGATIVO"
    else:
        emoji_resultado = "⚪"
        titulo = "DÍA NEUTRO"

    reporte = (
        f"{emoji_resultado} <b>REPORTE DIARIO — {titulo}</b>\n"
        f"📅 {fecha} · Cierre {hora}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Símbolo:          {SIMBOLO}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>P&L del día:</b>      ${pnl:+.2f}\n"
        f"📊 Operaciones:      {total_ops} ({buys} compras · {sells} ventas)\n"
        f"✅ Ganadores:        {len(ganadores)}\n"
        f"❌ Perdedores:       {len(perdedores)}\n"
        f"🎯 Tasa de aciertos: {tasa:.1f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Mejor trade:      ${mejor_trade:+.2f}\n"
        f"📉 Peor trade:       ${peor_trade:+.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕯 Velas procesadas: {velas}\n"
        f"🛡 Pérdida acumulada: ${perdida:.2f} / ${MAX_PERDIDA_DIARIA_USD:.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Bot EMA 3/8 · Hasta mañana!"
    )

    return reporte


def enviar_reporte_diario(estado: dict, operaciones: list):
    """Genera y envía el reporte diario por Telegram."""
    texto = generar_reporte_diario(estado, operaciones)
    enviado = enviar_telegram(texto)
    if enviado:
        print("[REPORTE] Reporte diario enviado a Telegram.")
    else:
        print("[REPORTE] Error enviando el reporte diario.")
    return enviado