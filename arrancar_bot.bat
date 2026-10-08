@echo off
title Bot de Trading EMA 3/8
color 0A

echo.
echo  ================================================
echo    BOT DE TRADING EMA 3/8  -  ThinkorSwim/Schwab
echo  ================================================
echo.
echo  Iniciando todos los sistemas...
echo.

:: Activar entorno virtual
call venv\Scripts\activate

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python no encontrado. Verificar instalacion.
    pause
    exit /b 1
)

:: ── PASO 1: Levantar el servidor del dashboard en segundo plano
echo  [1/2] Levantando servidor del dashboard...
start "Dashboard Server" /min cmd /c "python -m http.server 8080"
timeout /t 2 /nobreak >nul

:: ── PASO 2: Abrir el dashboard en el navegador
echo  [2/2] Abriendo dashboard en el navegador...
start "" "http://localhost:8080/dashboard.html"
timeout /t 1 /nobreak >nul

:: ── PASO 3: Arrancar el bot (en esta ventana)
echo.
echo  ================================================
echo   Dashboard: http://localhost:8080/dashboard.html
echo   Para apagar todo: cerra esta ventana
echo  ================================================
echo.

python main.py

:: Si llega aca, el bot se detuvo
echo.
echo  ================================================
echo   El bot se detuvo. Revisa bot.log para detalles.
echo  ================================================

:: Cerrar el servidor del dashboard
echo  Cerrando servidor del dashboard...
taskkill /fi "WINDOWTITLE eq Dashboard Server" /f >nul 2>&1

pause