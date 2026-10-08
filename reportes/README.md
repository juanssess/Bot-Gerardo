# Operaciones y resultados del bot

`operaciones.csv` contiene aperturas y cierres identificables en los registros disponibles: precios, ganancias, pérdidas y comisiones cuando fueron registradas. `ultima_sesion.json` muestra una captura del estado financiero más reciente.

El P&L del bot se calcula en modo paper; estos datos no acreditan inversiones u operaciones reales en la cuenta del broker. El campo `modo` de la captura conserva el valor informado por el bot.

Las fechas se conservan tal como aparecen en los logs: los históricos pueden tener solamente hora, sin fecha ni año. No se infieren fechas ni se suman registros de distintas sesiones, que pueden repetirse tras reinicios. Los campos ausentes quedan vacíos; el P&L histórico no se trata como neto cuando no informa comisiones.

Esta es una captura puntual; no se actualiza automáticamente. Los registros técnicos y las credenciales no se publican.
