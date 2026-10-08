"""
Cambia la estrategia del bot entre "original" e "invertida".

Uso:
    python3 cambiar_estrategia.py original
    python3 cambiar_estrategia.py invertida
    python3 cambiar_estrategia.py actual      → dice cuál está puesta

Copia los archivos de Estrategias/<nombre>/ a la carpeta del bot y cambia en .env
solo los valores de estrategia (las claves de Schwab/Telegram no se tocan).
Antes de reemplazar, guarda lo que estaba en Estrategias/ultimo_reemplazado/.
"""

import os
import re
import shutil
import subprocess
import sys

ESTR = os.path.dirname(os.path.abspath(__file__))
BOT  = os.path.dirname(ESTR)
ENV  = os.path.join(BOT, ".env")


def estrategia_actual() -> str:
    with open(ENV) as f:
        m = re.search(r"^INVERTIR_ESTRATEGIA=(\S*)", f.read(), re.M)
    return "invertida" if m and m.group(1) == "1" else "original"


def bot_corriendo() -> bool:
    r = subprocess.run(["pgrep", "-f", "python3 main.py"], capture_output=True)
    return r.returncode == 0


def cambiar(nombre: str) -> str:
    origen = os.path.join(ESTR, nombre)
    if not os.path.isdir(origen):
        raise SystemExit(f"No existe la estrategia '{nombre}' (opciones: original, invertida)")
    if bot_corriendo():
        raise SystemExit("El bot está corriendo. Cerralo primero y volvé a intentar.")

    respaldo = os.path.join(ESTR, "ultimo_reemplazado")
    shutil.rmtree(respaldo, ignore_errors=True)
    os.makedirs(respaldo)
    shutil.copy2(ENV, respaldo)

    for archivo in sorted(os.listdir(origen)):
        if archivo == "valores.env":
            continue
        destino = os.path.join(BOT, archivo)
        if os.path.exists(destino):
            shutil.copy2(destino, respaldo)
        shutil.copy2(os.path.join(origen, archivo), destino)

    with open(ENV) as f:
        env = f.read()
    with open(os.path.join(origen, "valores.env")) as f:
        for linea in f:
            linea = linea.strip()
            if not linea or "=" not in linea:
                continue
            clave = linea.split("=", 1)[0]
            if re.search(rf"^{clave}=", env, re.M):
                env = re.sub(rf"^{clave}=.*$", linea, env, flags=re.M)
            else:
                env = env.rstrip("\n") + f"\n{linea}\n"
    with open(ENV, "w") as f:
        f.write(env)

    return f"Estrategia '{nombre}' puesta. Ya podés arrancar el bot normalmente."


if __name__ == "__main__":
    pedido = sys.argv[1] if len(sys.argv) > 1 else "actual"
    if pedido == "actual":
        print(estrategia_actual())
    else:
        print(cambiar(pedido))
