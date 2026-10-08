import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID


def enviar_telegram(mensaje: str) -> bool:
    """
    Envía un mensaje a Telegram. Retorna True si fue exitoso.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       mensaje,
        "parse_mode": "HTML",
    }
    try:
        respuesta = requests.post(url, data=payload, timeout=10)
        if respuesta.status_code == 200:
            return True
        else:
            print(f"[TELEGRAM] Error HTTP {respuesta.status_code}: {respuesta.text}")
            return False
    except requests.exceptions.Timeout:
        print("[TELEGRAM] Timeout — no se pudo conectar a Telegram.")
        return False
    except requests.exceptions.ConnectionError:
        print("[TELEGRAM] Sin conexión a internet.")
        return False
    except Exception as e:
        print(f"[TELEGRAM] Error inesperado: {e}")
        return False