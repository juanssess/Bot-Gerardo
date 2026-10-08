# probar_historial_schwab.py
import schwab
from config import SCHWAB_APP_KEY, SCHWAB_APP_SECRET

client = schwab.auth.client_from_token_file(
    api_key    = SCHWAB_APP_KEY,
    app_secret = SCHWAB_APP_SECRET,
    token_path = "token.json",
)

simbolo = "/MESU26"
resp = client.get_price_history_every_minute(simbolo)
print("STATUS:", resp.status_code)

data = resp.json()
velas = data.get("candles", [])
print(f"Cantidad de velas devueltas: {len(velas)}")

if velas:
    print("Primera vela:", velas[0])
    print("Última vela: ", velas[-1])
else:
    print("Respuesta completa:", data)