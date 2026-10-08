property registro : "$HOME/Library/Logs/CambiarEstrategia.log"
property titulo : "Gerardo_Bot"

on anotar(txt)
	try
		do shell script "echo \"$(date '+%Y-%m-%d %H:%M:%S') " & txt & "\" >> " & registro
	end try
end anotar

on botCorriendo()
	try
		do shell script "pgrep -f 'python3 main.py'"
		return true
	on error
		return false
	end try
end botCorriendo

on aviso(txt, esError)
	activate
	if esError then
		display dialog txt buttons {"OK"} default button "OK" with icon stop with title titulo
	else
		display dialog txt buttons {"OK"} default button "OK" with title titulo
	end if
end aviso

-- Busca "CLAVE=valor" en la salida de ajustes.py ver
on valorDe(txt, clave)
	repeat with linea in paragraphs of txt
		if linea starts with (clave & "=") then return text ((length of clave) + 2) thru -1 of linea
	end repeat
	return "?"
end valorDe

on avisoReinicio()
	if botCorriendo() then aviso("⚠️ El bot está funcionando: el cambio se aplica cuando lo reinicies (Detener bot → Arrancar bot).", false)
end avisoReinicio

anotar("app abierta")
activate

set appPath to POSIX path of (path to me)
set botDir to do shell script "dirname " & quoted form of appPath
set py to quoted form of (botDir & "/.venv/bin/python")
set ajustes to py & " " & quoted form of (botDir & "/Estrategias/ajustes.py")
set lanzador to quoted form of (botDir & "/Arrancar_Bot-2.command")

repeat
	try
		set a to do shell script ajustes & " ver"
	on error errMsg
		anotar("ERROR leyendo ajustes: " & errMsg)
		aviso("No pude leer los ajustes:" & return & errMsg, true)
		return
	end try
	set estr to valorDe(a, "ESTRATEGIA")
	set emaR to valorDe(a, "EMA_RAPIDA")
	set emaL to valorDe(a, "EMA_LENTA")
	set tp to valorDe(a, "TAKE_PROFIT_PUNTOS")
	set sl to valorDe(a, "STOP_LOSS_PUNTOS")
	set tpTxt to tp & " pts (" & valorDe(a, "TAKE_TICKS") & " ticks)"
	if sl is "0" then
		set slTxt to "desactivado"
	else
		set slTxt to sl & " pts (" & valorDe(a, "STOP_TICKS") & " ticks)"
	end if
	if estr is "invertida" then
		set estrTxt to "INVERTIDA (cruce alcista vende)"
	else
		set estrTxt to "ORIGINAL (cruce alcista compra)"
	end if

	set corriendo to botCorriendo()
	if corriendo then
		set estadoTxt to "🟢 El bot está FUNCIONANDO"
		set botonBot to "Detener bot"
	else
		set estadoTxt to "⚪️ El bot está apagado"
		set botonBot to "Arrancar bot"
	end if

	activate
	set eleccion to button returned of (display dialog estadoTxt & return & return & ¬
		"Estrategia:   " & estrTxt & return & ¬
		"EMAs:           " & emaR & " / " & emaL & return & ¬
		"Take profit:  " & tpTxt & return & ¬
		"Stop loss:     " & slTxt ¬
		buttons {"Salir", "Ajustes", botonBot} default button botonBot with title titulo)
	anotar("menú: " & eleccion)

	if eleccion is "Salir" then return

	if eleccion is "Arrancar bot" then
		do shell script "open " & lanzador
		anotar("bot arrancado (" & estr & " EMA " & emaR & "/" & emaL & " TP " & tp & " SL " & sl & ")")
		-- Esperar a que el bot levante (hasta 20 s) y volver al menú, sin cerrar la app
		repeat 20 times
			if botCorriendo() then exit repeat
			delay 1
		end repeat
		if not botCorriendo() then aviso("⚠️ El bot todavía no arrancó. Fijate la ventana de Terminal por si muestra algún error.", true)
	end if

	if eleccion is "Detener bot" then
		activate
		set seguro to button returned of (display dialog "¿Detener el bot?" & return & return & "Si hay una posición abierta, queda abierta (igual que al cerrar la ventana de Terminal)." buttons {"No", "Sí, detener"} default button "No" with title titulo)
		if seguro is "Sí, detener" then
			do shell script "pkill -TERM -f 'python3 main.py'; exit 0"
			delay 3
			anotar("bot detenido")
		end if
	end if

	if eleccion is "Ajustes" then
		set opEstr to "Estrategia:  " & estrTxt
		set opR to "EMA rápida:  " & emaR
		set opL to "EMA lenta:  " & emaL
		set opTP to "Take profit:  " & tpTxt
		set opSL to "Stop loss:  " & slTxt
		activate
		set item_ to choose from list {opEstr, opR, opL, opTP, opSL} with title titulo with prompt "¿Qué querés cambiar?" OK button name "Cambiar" cancel button name "Volver"
		if item_ is not false then
			set item_ to item 1 of item_
			set clave to ""
			if item_ is opEstr then
				activate
				set nueva to button returned of (display dialog "Estrategia puesta ahora: " & estrTxt & return & return & "Cada estrategia guarda sus propias EMAs, TP y SL." buttons {"Cancelar", "Original", "Invertida"} default button "Cancelar" with title titulo)
				if nueva is not "Cancelar" then
					try
						set res to do shell script ajustes & " estrategia " & quoted form of nueva
						anotar("estrategia: " & nueva)
						aviso("✅ " & res, false)
						avisoReinicio()
					on error errMsg
						aviso("❌ " & errMsg, true)
					end try
				end if
			else if item_ is opR then
				set clave to "EMA_RAPIDA"
				set pregunta to "EMA rápida (número entero, menor que la lenta):"
				set actualV to emaR
			else if item_ is opL then
				set clave to "EMA_LENTA"
				set pregunta to "EMA lenta (número entero, mayor que la rápida):"
				set actualV to emaL
			else if item_ is opTP then
				set clave to "TAKE_PROFIT_PUNTOS"
				set pregunta to "Take profit en PUNTOS (1 punto = 4 ticks · ej: 3.5 = 14 ticks):"
				set actualV to tp
			else if item_ is opSL then
				set clave to "STOP_LOSS_PUNTOS"
				set pregunta to "Stop loss en PUNTOS (1 punto = 4 ticks · 0 = sin stop loss):"
				set actualV to sl
			end if
			if clave is not "" then
				activate
				set r to display dialog pregunta default answer actualV buttons {"Cancelar", "Guardar"} default button "Guardar" with title titulo
				if button returned of r is "Guardar" then
					try
						set res to do shell script ajustes & " poner " & clave & " " & quoted form of (text returned of r)
						anotar("ajuste: " & res)
						aviso("✅ Guardado.", false)
						avisoReinicio()
					on error errMsg
						anotar("ERROR ajuste " & clave & ": " & errMsg)
						aviso("❌ " & errMsg, true)
					end try
				end if
			end if
		end if
	end if
end repeat
