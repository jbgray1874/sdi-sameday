@echo off
title SDI Studio Brief - keep running
rem only one copy: it is started both from the Startup folder and from the Run key (whichever Windows runs first)
echo %date% %time% autostart launched >> "%~dp0newsys\tools\autostart.log"
python "%~dp0newsys\one_autostart.py" || (echo %date% %time% another copy running - this one quits >> "%~dp0newsys\tools\autostart.log" & exit /b)
echo %date% %time% this copy is the loop >> "%~dp0newsys\tools\autostart.log"
cd /d "%~dp0"

rem Runs from the Windows Startup folder, so Studio Brief starts by itself whenever
rem this laptop is switched on and signed in. Then it checks every 5 minutes and
rem starts it again if it has stopped. Close this window to stop the checking.
rem (It cannot run while the laptop itself is off - that needs a server.)

rem give Windows and the network a minute to settle after sign-in
timeout /t 60 /nobreak >nul

rem Studio Brief reads Jono's calendar and emails through Outlook: open it ONCE at sign-in, minimised, if it isn't
rem already running. Never again inside the loop - if you close Outlook, it stays closed (it used to pop back up every 5 minutes).
tasklist /FI "IMAGENAME eq OUTLOOK.EXE" 2>nul | find /I "OUTLOOK.EXE" >nul || (start "" /min outlook.exe & timeout /t 45 /nobreak >nul)

:loop
rem Outlook stuck in the background with no window (22 Oct 2026): end it and open it again
"%~dp0.venv-gpu\Scripts\python.exe" "%~dp0newsys\outlook_health.py" >> "%~dp0newsys\tools\outlook_health.log" 2>&1

netstat -ano | findstr /r /c:":5003 .*LISTENING" >nul
if errorlevel 1 (
  echo %date% %time%  Studio Brief not running - starting it
  call "%~dp0Start_Brief_Manager.bat" quiet
)
rem WhatsApp: keep the tunnel up and tell Meta its address (it changes after every restart)
python "%~dp0newsys\wa_tunnel.py" >> "%~dp0newsys\tools\wa_tunnel.log" 2>&1
rem Brief Lite (AM/PM concept briefs) on port 5020
netstat -ano | findstr /r /c:":5020 .*LISTENING" >nul
if errorlevel 1 if exist "%~dp0brief_lite\lite_app.py" (
  echo %date% %time%  Brief Lite not running - starting it
  start "SDI Brief Lite" /min "%~dp0.venv-gpu\Scripts\python.exe" "%~dp0brief_lite\lite_app.py"
)
rem SDI Craft (what the tools learn - Showroom, Flow, Recall) on port 5030
netstat -ano | findstr /r /c:":5030 .*LISTENING" >nul
if errorlevel 1 if exist "%~dp0craft\craft_site.py" (
  echo %date% %time%  SDI Craft not running - starting it
  start "SDI Craft" /min "%~dp0.venv-gpu\Scripts\python.exe" "%~dp0craft\craft_site.py"
)
rem SDI Presentation Intelligence (Deck Intelligence) on port 5050
netstat -ano | findstr /r /c:":5050 .*LISTENING" >nul
if errorlevel 1 if exist "%~dp0deck_studio\deck_app.py" (
  echo %date% %time%  Deck Intelligence not running - starting it
  call "%~dp0Start_Deck_Intelligence.bat" quiet
)
rem Brief Lite on phones: keep its HTTPS link (Cloudflare tunnel to 5020) running; the link is in brief_lite\PHONE_LINK.txt
python "%~dp0brief_lite\lite_tunnel.py" >nul 2>&1
timeout /t 300 /nobreak >nul
goto loop
