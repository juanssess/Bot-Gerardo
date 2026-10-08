"""
Ajustes del bot que usa la app "Gerardo Bot".

Uso:
    python3 ajustes.py ver                       → muestra los ajustes actuales (clave=valor)
    python3 ajustes.py estrategia original       → pone la estrategia original
    python3 ajustes.py estrategia invertida      → pone la estrategia invertida
    python3 ajustes.py poner EMA_RAPIDA 9        → cambia un ajuste

Cada estrategia guarda sus propios valores en Estrategias/<nombre>/valores.env.
Al cambiar un ajuste se escribe en .env (lo que usa el bot) y en los valores de la
estrategia que está puesta, así no se pierde al pasar de una estrategia a la otra.
Las claves de Schwab y Telegram del .env no se tocan nunca.
Los cambios se aplican la próxima vez que arranca el bot.
"""

import os
import re
import sys

ESTR = os.path.dirname(os.path.abspath(__file__))
BOT  = os.path.dirname(ESTR)
ENV  = os.path.join(BOT, ".env")

ESTRATEGIAS = ("original", "invertida")
TICK = {"/ES": 0.25, "/MES": 0.25, "/NQ": 0.25, "/MNQ": 0.25}


# ── Lectura / escritura de archivos .env ──
def leer(path: str) -> dict:
    vals = {}
    if os.path.exists(path):
        with open(path) as f:
            for linea in f:
                m = re.match(r"^([A-Z_]+)=(.*)$", linea.strip())
                if m:
                    vals[m.group(1)] = m.group(2)
    return vals


def escribir(path: str, cambios: dict):
    texto = open(path).read() if os.path.exists(path) else ""
    for clave, valor in cambios.items():
        linea = f"{clave}={valor}"
        if re.search(rf"^{clave}=", texto, re.M):
            texto = re.sub(rf"^{clave}=.*$", linea, texto, flags=re.M)
        else:
            texto = texto.rstrip("\n") + ("\n" if texto else "") + linea + "\n"
    with open(path, "w") as f:
        f.write(texto)


def valores_estrategia(nombre: str) -> str:
    return os.path.join(ESTR, nombre, "valores.env")


def estrategia_actual() -> str:
    return "invertida" if leer(ENV).get("INVERTIR_ESTRATEGIA") == "1" else "original"


# ── Validación ──
def _num(valor: str) -> float:
    try:
        return float(valor.replace(",", "."))
    except ValueError:
        raise SystemExit(f"'{valor}' no es un número.")


def _puntos(valor: str, nombre: str, permitir_cero: bool) -> str:
    n = _num(valor)
    if n < 0 or (n == 0 and not permitir_cero):
        raise SystemExit(f"El {nombre} tiene que ser mayor a 0.")
    if n > 100:
        raise SystemExit(f"El {nombre} de {n:g} puntos es demasiado grande (máximo 100).")
    tick = TICK.get(leer(ENV).get("SIMBOLO", "/ES"))
    if tick and round(n / tick, 6) % 1 != 0:
        raise SystemExit(f"El {nombre} tiene que ir de a {tick:g} puntos (1 tick). Ej: 3, 3.25, 3.5, 3.75.")
    return f"{n:g}"


def validar(clave: str, valor: str) -> str:
    env = leer(ENV)
    if clave in ("EMA_RAPIDA", "EMA_LENTA"):
        n = _num(valor)
        if n != int(n) or not 2 <= n <= 100:
            raise SystemExit("La EMA tiene que ser un número entero entre 2 y 100.")
        n = int(n)
        rapida = n if clave == "EMA_RAPIDA" else int(env.get("EMA_RAPIDA", "7"))
        lenta  = n if clave == "EMA_LENTA"  else int(env.get("EMA_LENTA", "10"))
        if rapida >= lenta:
            raise SystemExit(f"La EMA rápida ({rapida}) tiene que ser MENOR que la EMA lenta ({lenta}).")
        return str(n)
    if clave == "TAKE_PROFIT_PUNTOS":
        return _puntos(valor, "take profit", permitir_cero=False)
    if clave == "STOP_LOSS_PUNTOS":
        return _puntos(valor, "stop loss", permitir_cero=True)
    raise SystemExit(f"Ajuste desconocido: {clave}")


# ── Acciones ──
def ver():
    env = leer(ENV)
    print(f"ESTRATEGIA={estrategia_actual()}")
    for clave, defecto in (("EMA_RAPIDA", "7"), ("EMA_LENTA", "10"),
                           ("TAKE_PROFIT_PUNTOS", "3.5"), ("STOP_LOSS_PUNTOS", "0")):
        print(f"{clave}={env.get(clave, defecto)}")
    tick = TICK.get(env.get("SIMBOLO", "/ES"))
    for clave, defecto in (("TAKE_PROFIT_PUNTOS", "3.5"), ("STOP_LOSS_PUNTOS", "0")):
        ticks = f"{_num(env.get(clave, defecto)) / tick:g}" if tick else "?"
        print(f"{clave.split('_')[0]}_TICKS={ticks}")


def poner_estrategia(nombre: str):
    if nombre not in ESTRATEGIAS:
        raise SystemExit(f"No existe la estrategia '{nombre}' (opciones: original, invertida)")
    escribir(ENV, leer(valores_estrategia(nombre)))
    print(f"Estrategia {nombre.upper()} puesta.")


def poner(clave: str, valor: str):
    valor = validar(clave, valor)
    escribir(ENV, {clave: valor})
    escribir(valores_estrategia(estrategia_actual()), {clave: valor})
    print(f"{clave}={valor}")


if __name__ == "__main__":
    args = sys.argv[1:] or ["ver"]
    if args[0] == "ver":
        ver()
    elif args[0] == "estrategia" and len(args) == 2:
        poner_estrategia(args[1])
    elif args[0] == "poner" and len(args) == 3:
        poner(args[1], args[2])
    else:
        raise SystemExit(__doc__)
