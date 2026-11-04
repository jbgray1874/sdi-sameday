@echo off
rem Update SDI Same Day Intelligence on this server from K: - double-click to run.
rem 1 copies the latest code over C:\SDI_Automation (never touches .venv-gpu, out, backups or lite.db)
rem 2 checks the copy matches K:   3 restarts the app   4 checks the running app is the new version
setlocal
set "SRC=K:\IT\AI & Automation\Design\SDI Same Day Intelligence\SDI_Automation"
set "DST=C:\SDI_Automation"
set "PY=%DST%\.venv-gpu\Scripts\python.exe"

echo ============================================================
echo  SDI Same Day Intelligence - update from K:
echo ============================================================
if not exist "%SRC%\brief_lite\VERSION.txt" (
  echo PROBLEM: K: is not reachable, or the published files are missing:
  echo   %SRC%
  echo Check the K: drive is mapped on this server, then run this again. Nothing was changed.
  goto :fail
)
if not exist "%PY%" (
  echo PROBLEM: Python was not found at %PY%
  echo The first install from DEPLOY_GUIDE.html has not been done on this server. Nothing was changed.
  goto :fail
)
set /p NEWVER=<"%SRC%\brief_lite\VERSION.txt"
echo Latest on K: %NEWVER%
echo.
echo [1/4] Copying the latest files from K: ...
robocopy "%SRC%" "%DST%" /E /XD .venv-gpu out backups /XF lite.db /R:2 /W:2 /NFL /NDL /NJH /NJS /NP
if %ERRORLEVEL% GEQ 8 (
  echo PROBLEM: the copy failed ^(robocopy code %ERRORLEVEL%^). A file may be locked or K: dropped out.
  echo Close anything using C:\SDI_Automation and run this again. The app was NOT restarted.
  goto :fail
)

echo [2/4] Checking the copy ...
set /p GOTVER=<"%DST%\brief_lite\VERSION.txt"
if not "%GOTVER%"=="%NEWVER%" (
  echo PROBLEM: the files on C: are %GOTVER%, but K: has %NEWVER%. The copy did not complete.
  goto :fail
)
echo   OK - C:\SDI_Automation now has %NEWVER%

echo [3/4] Restarting Same Day ...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -match 'lite_app' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 3 /nobreak >nul
start "SDI Same Day" /min "%PY%" "%DST%\brief_lite\lite_app.py"

echo [4/4] Waiting for it to start (up to 2 minutes) ...
powershell -NoProfile -Command "$want='%NEWVER%'; for($i=0;$i -lt 40;$i++){ Start-Sleep 3; try{ $s=Invoke-RestMethod http://127.0.0.1:5020/api/status -TimeoutSec 5; if($s.version -eq $want){ Write-Host ('  OK - Same Day is running ' + $s.version + '  (OpenAI key: ' + $s.openai_key + ')'); exit 0 } else { $last=$s.version } } catch {} }; if($last){ Write-Host ('PROBLEM: Same Day started but is running ' + $last + ', not ' + $want + '. Run this again.') } else { Write-Host 'PROBLEM: Same Day did not start within 2 minutes. Open the minimised SDI Same Day window to see the error, or run C:\SDI_Automation\.venv-gpu\Scripts\python.exe C:\SDI_Automation\brief_lite\lite_app.py in a command window.' }; exit 1"
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  SUCCESS - Same Day is updated to %NEWVER% and running.
echo  Refresh the page in the browser (Ctrl+F5).
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ============================================================
echo  NOT UPDATED - see the PROBLEM line above. Send a screenshot of
echo  this window to Muhammad if it is not clear what to do.
echo ============================================================
pause
exit /b 1
