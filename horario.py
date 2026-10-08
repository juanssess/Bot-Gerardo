"""
Horario de operación — en hora de Nueva York (la del CME)
=========================================================
Los futuros de índices (/ES, /MES, /NQ, /MNQ) operan:
    domingo 18:00 → viernes 17:00 (hora NY), con pausa diaria de 17:00 a 18:00.

El bot opera de APERTURA_NY a CIERRE_NY (cierra 30 min antes de la pausa).
Al estar en hora NY, el cambio de horario de verano de EE.UU. se acomoda solo:
    - con horario de verano de EE.UU. (mar–nov): 19:00 → 17:30 en Argentina
    - sin horario de verano (nov–mar):           20:00 → 18:30 en Argentina

Sesión: como en el CME, la sesión que abre a las 18:00 NY pertenece al día
siguiente (la del domingo a la noche es la del lunes). Los contadores del día
(P&L, pérdida máxima, operaciones) se reinician al abrir cada sesión.

No contempla feriados de EE.UU.: ese día el bot ve el precio quieto y no opera.
"""

from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

ZONA_NY     = ZoneInfo("America/New_York")
APERTURA_NY = time(18, 0)
CIERRE_NY   = time(16, 30)

_DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _ahora_ny(ahora: datetime = None) -> datetime:
    return (ahora or datetime.now().astimezone()).astimezone(ZONA_NY)


def es_horario_operacion(ahora: datetime = None) -> bool:
    ny = _ahora_ny(ahora)
    dia, hora = ny.weekday(), ny.time()      # lunes=0 … domingo=6
    if dia == 5:                             # sábado: cerrado todo el día
        return False
    if dia == 6:                             # domingo: abre a las 18:00
        return hora >= APERTURA_NY
    if dia == 4:                             # viernes: cierra y no reabre hasta el domingo
        return hora < CIERRE_NY
    return hora < CIERRE_NY or hora >= APERTURA_NY


def sesion_actual(ahora: datetime = None) -> date:
    """Fecha de la sesión (convención CME): desde las 18:00 NY ya cuenta como el día siguiente."""
    ny = _ahora_ny(ahora)
    d = ny.date() + timedelta(days=1) if ny.time() >= APERTURA_NY else ny.date()
    while d.weekday() >= 5:                  # sábado/domingo → la sesión es la del lunes
        d += timedelta(days=1)
    return d


def proxima_apertura(ahora: datetime = None) -> datetime:
    """Próxima apertura del bot (en hora local de la Mac)."""
    ny = _ahora_ny(ahora)
    d = ny.date() if ny.time() < APERTURA_NY else ny.date() + timedelta(days=1)
    while d.weekday() in (4, 5):             # viernes y sábado no abre a la noche
        d += timedelta(days=1)
    return datetime.combine(d, APERTURA_NY, tzinfo=ZONA_NY).astimezone()


def texto_proxima_apertura(ahora: datetime = None) -> str:
    """Ej. '19:00' si es hoy, 'dom 19:00' si es otro día."""
    local = (ahora or datetime.now().astimezone()).astimezone()
    ap = proxima_apertura(ahora)
    if ap.date() == local.date():
        return ap.strftime("%H:%M")
    return f"{_DIAS[ap.weekday()]} {ap.strftime('%H:%M')}"


def horario_local(ahora: datetime = None) -> tuple:
    """Apertura y cierre del bot en hora local, para hoy. Ej. ('19:00', '17:30')."""
    d = _ahora_ny(ahora).date()
    ap = datetime.combine(d, APERTURA_NY, tzinfo=ZONA_NY).astimezone()
    ci = datetime.combine(d, CIERRE_NY,   tzinfo=ZONA_NY).astimezone()
    return ap.strftime("%H:%M"), ci.strftime("%H:%M")
