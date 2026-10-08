"""
Diario del bot en la app Notas de la Mac
========================================
Cada vez que se prende el bot (y cada sesión nueva si queda prendido varios días)
se crea una nota en la carpeta "Gerardo_Bot" de la app Notas con:
    - una explicación en palabras de lo que pasó (mercado, señales, resultado, incidentes)
    - el resultado en números
    - la lista de operaciones
    - los eventos importantes

La nota se actualiza después de cada operación, cada 30 min y al apagar el bot.
Se escribe con AppleScript (osascript) en un hilo aparte, así el bot no se frena
si Notas tarda. La primera vez macOS pide permiso para que Terminal controle Notas.
"""

import html
import logging
import queue
import subprocess
import threading
import time
from datetime import datetime

log = logging.getLogger(__name__)

CARPETA_NOTAS    = "Gerardo_Bot"
ACTUALIZAR_CADA_SEG = 30 * 60

_DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

# AppleScript: actualiza la nota si ya existe (por id), si no la crea en la carpeta.
# El título de la nota es la primera línea del cuerpo.
_SCRIPT = '''
on run argv
    set nombreCarpeta to item 1 of argv
    set cuerpo to item 2 of argv
    set idNota to item 3 of argv
    tell application "Notes"
        if idNota is not "" then
            try
                set n to note id idNota
                set body of n to cuerpo
                return id of n
            end try
        end if
        tell default account
            if not (exists folder nombreCarpeta) then make new folder with properties {name:nombreCarpeta}
            set n to make new note at folder nombreCarpeta with properties {body:cuerpo}
        end tell
        return id of n
    end tell
end run
'''


def _hora(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _fecha(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    return f"{_DIAS[d.weekday()]} {d:%d/%m}"


def _duracion(seg: float) -> str:
    m = int(seg // 60)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} min"


def _money(n: float) -> str:
    return f"{'+' if n > 0 else '−' if n < 0 else ''}${abs(n):,.2f}"


def _pts(n: float) -> str:
    return f"{'+' if n > 0 else '−' if n < 0 else ''}{abs(n):.2f}"


class Diario:
    def __init__(self, contrato: str, params: dict):
        self.contrato = contrato
        self.params   = params          # tp_pts, sl_pts, valor_punto, comision, max_perdida, vela_min
        self._cola    = queue.Queue()
        self._hilo    = threading.Thread(target=self._trabajar, daemon=True)
        self._hilo.start()
        self._nueva(time.time())

    # ─────────────────────────── registro ───────────────────────────
    def _nueva(self, inicio: float):
        self.inicio        = inicio
        self.id_nota       = ""
        self.p_primero     = None
        self.p_ultimo      = None
        self.p_min         = None
        self.p_max         = None
        self.cruces        = {"detectados": 0, "confirmados": 0, "descartados": 0}
        self.eventos       = []            # (ts, texto)
        self.perdida_max   = 0.0
        self.ultima_escritura = 0.0

    def precio(self, p: float):
        if not p:
            return
        if self.p_primero is None:
            self.p_primero = p
        self.p_ultimo = p
        self.p_min = p if self.p_min is None else min(self.p_min, p)
        self.p_max = p if self.p_max is None else max(self.p_max, p)

    def cruce(self, que: str):
        self.cruces[que] += 1

    def evento(self, texto: str):
        self.eventos.append((time.time(), texto))

    # ─────────────────────────── armado ───────────────────────────
    def _explicacion(self, estado: dict, ops: list, fin: str, ahora: float) -> list:
        p = self.params
        parrafos = []

        # 1) Cuánto tiempo estuvo prendido
        dur = _duracion(ahora - self.inicio)
        if fin:
            parrafos.append(
                f"El bot estuvo prendido desde el {_fecha(self.inicio)} a las {_hora(self.inicio)} "
                f"hasta las {_hora(ahora)} ({dur}), operando <b>{self.contrato}</b> en modo PAPER "
                f"(simulado, sin plata real). Se apagó por: {fin}.")
        else:
            parrafos.append(
                f"El bot está prendido desde el {_fecha(self.inicio)} a las {_hora(self.inicio)} "
                f"({dur} hasta ahora), operando <b>{self.contrato}</b> en modo PAPER (simulado, sin plata real). "
                f"<i>Nota en curso — última actualización {_hora(ahora)}.</i>")

        # 2) Qué hizo el mercado
        if self.p_primero is not None:
            rango  = self.p_max - self.p_min
            cambio = self.p_ultimo - self.p_primero
            if rango and abs(cambio) < rango * 0.25:
                tipo = "sin una dirección clara (lateral)"
            elif cambio > 0:
                tipo = "con tendencia alcista"
            else:
                tipo = "con tendencia bajista"
            parrafos.append(
                f"En ese tiempo el {self.contrato} se movió entre {self.p_min:,.2f} y {self.p_max:,.2f} "
                f"(un rango de {rango:.2f} puntos). Arrancó en {self.p_primero:,.2f} y "
                f"{'terminó' if fin else 'va'} en {self.p_ultimo:,.2f} ({_pts(cambio)} pts), o sea un mercado {tipo}.")
        else:
            parrafos.append("No llegó a leer precios en horario de operación (estuvo fuera de horario o sin conexión).")

        # 3) Señales
        c = self.cruces
        if c["detectados"]:
            parrafos.append(
                f"La estrategia busca cruces de la EMA {p.get('ema_rapida', 7)} con la EMA {p.get('ema_lenta', 10)} en velas de {p['vela_min']} min y entra "
                f"solo si el cruce se mantiene al cierre de la vela siguiente. Detectó <b>{c['detectados']}</b> "
                f"cruce{'s' if c['detectados'] != 1 else ''}: {c['confirmados']} se confirmaron y "
                f"{c['descartados']} se descartaron porque en la vela siguiente se dieron vuelta.")
        else:
            parrafos.append(
                f"No hubo cruces de EMA {p.get('ema_rapida', 7)} y EMA {p.get('ema_lenta', 10)} en velas de {p['vela_min']} min"
                f"{' mientras no había posición abierta' if ops else ''}, así que no hubo señales nuevas.")

        # 4) Resultado
        if ops:
            gan   = [o for o in ops if o["resultado"] > 0]
            perd  = [o for o in ops if o["resultado"] <= 0]
            neto  = sum(o["resultado"] for o in ops)
            bruto = sum(o.get("bruto", o["resultado"]) for o in ops)
            com   = sum(o.get("comision", 0) for o in ops)
            pts   = sum(o.get("puntos", 0) for o in ops)
            acierto = len(gan) / len(ops) * 100
            mejor = max(ops, key=lambda o: o["resultado"])
            peor  = min(ops, key=lambda o: o["resultado"])
            parrafos.append(
                f"Hizo <b>{len(ops)} operaci{'ones' if len(ops) != 1 else 'ón'}</b>: {len(gan)} ganadora{'s' if len(gan) != 1 else ''} "
                f"y {len(perd)} perdedora{'s' if len(perd) != 1 else ''} ({acierto:.0f}% de acierto). "
                f"Sumó {_pts(pts)} puntos ({_money(bruto)} bruto); descontando ${com:,.2f} de comisiones, "
                f"el resultado neto fue <b>{_money(neto)}</b>.")
            if len(ops) > 1:
                parrafos.append(
                    f"La mejor fue un {mejor['posicion']} cerrado a las {mejor['hora'][:5]} ({_money(mejor['resultado'])}) "
                    f"y la peor un {peor['posicion']} cerrado a las {peor['hora'][:5]} ({_money(peor['resultado'])}).")
            # Punto de equilibrio con TP/SL y comisiones
            tp_usd = p["tp_pts"] * p["valor_punto"]
            sl_usd = p["sl_pts"] * p["valor_punto"]
            if tp_usd > 0 and sl_usd > 0:
                equilibrio = (sl_usd + p["comision"]) / (tp_usd + sl_usd) * 100
                parrafos.append(
                    f"Con TP de {p['tp_pts']:g} pts y SL de {p['sl_pts']:g} pts, más la comisión, para no perder plata "
                    f"hace falta acertar más del {equilibrio:.0f}% de las operaciones. En esta sesión acertó el "
                    f"{acierto:.0f}%, {'por encima' if acierto > equilibrio else 'por debajo'} de ese número.")
        else:
            parrafos.append("No abrió ni cerró operaciones.")

        # 5) Riesgo
        perdida = estado.get("perdida_acumulada", 0.0)
        if perdida:
            parrafos.append(
                f"La pérdida acumulada (suma de las operaciones perdedoras) llegó a ${perdida:,.2f}"
                + (f" de un tope diario de ${p['max_perdida']:,.0f}." if p['max_perdida'] > 0 else " (sin tope diario)."))

        # 6) Posición que quedó abierta
        if estado.get("posicion_abierta"):
            parrafos.append(
                f"{'Quedó' if fin else 'Hay'} abierta una posición <b>{estado['posicion_abierta']}</b> desde "
                f"{estado['precio_entrada']:,.2f} (TP {estado['take_profit_precio']}, SL {estado['stop_loss_precio']})"
                f"{'. El bot la retoma cuando lo prendas de nuevo' if fin else ''}.")

        # 7) Incidentes
        if self.eventos:
            parrafos.append(f"Hubo {len(self.eventos)} evento{'s' if len(self.eventos) != 1 else ''} para tener en cuenta (detalle abajo).")
        else:
            parrafos.append("Sin incidentes: no hubo cortes de conexión, errores ni problemas con el token.")
        return parrafos

    def _html(self, estado: dict, ops: list, fin: str, ahora: float) -> str:
        p = self.params
        neto = sum(o["resultado"] for o in ops)
        titulo = (f"Gerardo_Bot · {_fecha(self.inicio)} {_hora(self.inicio)} · {self.contrato} · "
                  f"{_money(neto)} · {len(ops)} op{'s' if len(ops) != 1 else ''}")
        partes = [f"<h1>{html.escape(titulo)}</h1>"]

        partes.append("<h2>Qué pasó</h2>")
        partes += [f"<div>{t}</div><br>" for t in self._explicacion(estado, ops, fin, ahora)]

        partes.append("<h2>Números</h2><ul>")
        gan = sum(1 for o in ops if o["resultado"] > 0)
        filas = [
            ("P&amp;L neto", _money(neto)),
            ("Comisiones", f"${sum(o.get('comision', 0) for o in ops):,.2f}"),
            ("Operaciones", f"{len(ops)} ({gan} ganada{'s' if gan != 1 else ''} / "
                            f"{len(ops) - gan} perdida{'s' if len(ops) - gan != 1 else ''})"),
            ("Cruces", f"{self.cruces['detectados']} detectados · {self.cruces['confirmados']} confirmados · "
                       f"{self.cruces['descartados']} descartados"),
            ("Pérdida acumulada", f"${estado.get('perdida_acumulada', 0):,.2f} / "
                                  + (f"${p['max_perdida']:,.0f}" if p['max_perdida'] > 0 else "sin límite")),
            ("Estrategia", f"EMA {p.get('ema_rapida', 7)}/{p.get('ema_lenta', 10)} · velas de {p['vela_min']} min · TP {p['tp_pts']:g} pts · SL {p['sl_pts']:g} pts · "
                           f"${p['valor_punto']:g} por punto · comisión ${p['comision']:.2f} por operación"),
        ]
        partes += [f"<li><b>{k}:</b> {v}</li>" for k, v in filas]
        partes.append("</ul>")

        partes.append("<h2>Operaciones</h2>")
        if ops:
            partes.append("<ul>")
            for o in ops:
                t_in, t_out = o.get("t_entrada"), o.get("t_salida")
                horas = f"{_hora(t_in)} → {_hora(t_out)}" if t_in and t_out else o["hora"][:5]
                dur = f" · {_duracion(t_out - t_in)}" if t_in and t_out else ""
                partes.append(
                    f"<li>{horas} · <b>{o['posicion']}</b> · {o['entrada']:,.2f} → {o['salida']:,.2f} · "
                    f"{_pts(o.get('puntos', 0))} pts · neto <b>{_money(o['resultado'])}</b> · "
                    f"{html.escape(o['motivo'])}{dur}</li>")
            partes.append("</ul>")
        else:
            partes.append("<div>Sin operaciones.</div>")

        if self.eventos:
            partes.append("<h2>Eventos</h2><ul>")
            partes += [f"<li>{_hora(ts)} · {html.escape(t)}</li>" for ts, t in self.eventos]
            partes.append("</ul>")
        return "".join(partes)

    # ─────────────────────────── escritura ───────────────────────────
    def actualizar(self, estado: dict, ops: list, fin: str = "", esperar: bool = False):
        """Encola la nota para escribirla. Con esperar=True (al apagar) espera a que se escriba."""
        ahora = time.time()
        self.ultima_escritura = ahora
        listo = threading.Event()
        self._cola.put((self._html(estado, ops, fin, ahora), listo))
        if esperar:
            listo.wait(timeout=20)

    def quizas_actualizar(self, estado: dict, ops: list):
        if time.time() - self.ultima_escritura >= ACTUALIZAR_CADA_SEG:
            self.actualizar(estado, ops)

    def cerrar_y_empezar_otra(self, estado: dict, ops: list, motivo: str):
        """Cierra la nota actual (ej. al empezar una sesión nueva) y arranca una nota nueva."""
        self.actualizar(estado, ops, fin=motivo, esperar=True)
        self._nueva(time.time())

    def _trabajar(self):
        avisado = False
        while True:
            cuerpo, listo = self._cola.get()
            # Si se juntaron varias versiones, escribimos solo la última
            while not self._cola.empty():
                listo.set()
                cuerpo, listo = self._cola.get()
            try:
                r = subprocess.run(
                    ["osascript", "-", CARPETA_NOTAS, cuerpo, self.id_nota],
                    input=_SCRIPT, capture_output=True, text=True, timeout=60,
                )
                if r.returncode == 0:
                    self.id_nota = r.stdout.strip()
                elif not avisado:
                    avisado = True
                    log.warning(f"No se pudo escribir en Notas: {r.stderr.strip()[:200]} "
                                f"— revisá Configuración del Sistema → Privacidad → Automatización → Terminal → Notas")
            except Exception as e:
                if not avisado:
                    avisado = True
                    log.warning(f"No se pudo escribir en Notas: {e}")
            finally:
                listo.set()
