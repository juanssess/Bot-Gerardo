"""
Estrategia de cruce de EMAs (rápida/lenta, ver config.py) con filtro ADX.
Usa OHLC real para calcular el True Range correctamente.
"""

import pandas as pd
import numpy as np
from config import ADX_MINIMO, EMA_RAPIDA, EMA_LENTA


def calcular_emas(velas: list) -> dict:
    """
    Calcula EMA rápida, EMA lenta y ADX a partir de velas OHLC.
    (Las claves siguen llamándose ema7/ema10 por compatibilidad.)
    """
    if not velas or len(velas) < max(20, EMA_LENTA + 2):
        return {
            "señal":        "ESPERANDO",
            "ema7_actual":  None,
            "ema10_actual": None,
            "diferencia":   None,
            "adx":          None,
        }

    if isinstance(velas[0], (int, float)):
        velas = [{"open": p, "high": p, "low": p, "close": p} for p in velas]

    df = pd.DataFrame(velas)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── EMAs sobre el cierre ──
    df["ema7"]  = df["close"].ewm(span=EMA_RAPIDA, adjust=False).mean()
    df["ema10"] = df["close"].ewm(span=EMA_LENTA,  adjust=False).mean()

    # ── True Range real ──
    df["close_prev"] = df["close"].shift(1)
    df["hl"]    = df["high"] - df["low"]
    df["h_cp"]  = (df["high"] - df["close_prev"]).abs()
    df["l_cp"]  = (df["low"]  - df["close_prev"]).abs()
    df["tr"]    = df[["hl", "h_cp", "l_cp"]].max(axis=1)

    # ── Directional Movement ──
    df["up_move"]   = df["high"].diff()
    df["down_move"] = -df["low"].diff()

    df["dm_pos"] = np.where(
        (df["up_move"] > df["down_move"]) & (df["up_move"] > 0),
        df["up_move"], 0.0
    )
    df["dm_neg"] = np.where(
        (df["down_move"] > df["up_move"]) & (df["down_move"] > 0),
        df["down_move"], 0.0
    )

    df["tr"]     = df["tr"].fillna(0)
    df["dm_pos"] = df["dm_pos"].astype(float)
    df["dm_neg"] = df["dm_neg"].astype(float)

    periodo = 14
    df["tr_smooth"]     = df["tr"].ewm(span=periodo, adjust=False).mean()
    df["dm_pos_smooth"] = df["dm_pos"].ewm(span=periodo, adjust=False).mean()
    df["dm_neg_smooth"] = df["dm_neg"].ewm(span=periodo, adjust=False).mean()

    tr_safe = df["tr_smooth"].replace(0, 0.0001)
    df["di_pos"] = (df["dm_pos_smooth"] / tr_safe) * 100
    df["di_neg"] = (df["dm_neg_smooth"] / tr_safe) * 100

    di_sum_safe = (df["di_pos"] + df["di_neg"]).replace(0, 0.0001)
    df["dx"]  = (abs(df["di_pos"] - df["di_neg"]) / di_sum_safe) * 100
    df["adx"] = df["dx"].ewm(span=periodo, adjust=False).mean()

    ema7_actual    = df["ema7"].iloc[-1]
    ema10_actual   = df["ema10"].iloc[-1]
    ema7_anterior  = df["ema7"].iloc[-2]
    ema10_anterior = df["ema10"].iloc[-2]
    diferencia     = round(abs(ema7_actual - ema10_actual), 4)

    adx_val = df["adx"].iloc[-1]
    adx_actual = round(float(adx_val), 2) if pd.notna(adx_val) else 0.0

    if adx_actual < ADX_MINIMO:
        return {
            "señal":        "LATERAL",
            "ema7_actual":  round(ema7_actual,  4),
            "ema10_actual": round(ema10_actual, 4),
            "diferencia":   diferencia,
            "adx":          adx_actual,
        }

    if ema7_anterior <= ema10_anterior and ema7_actual > ema10_actual:
        señal = "COMPRAR"
    elif ema7_anterior >= ema10_anterior and ema7_actual < ema10_actual:
        señal = "VENDER"
    else:
        señal = "MANTENER"

    return {
        "señal":         señal,
        "ema7_actual":   round(ema7_actual,    4),
        "ema10_actual":  round(ema10_actual,   4),
        "ema7_anterior": round(ema7_anterior,  4),
        "ema10_anterior":round(ema10_anterior, 4),
        "diferencia":    diferencia,
        "adx":           adx_actual,
    }