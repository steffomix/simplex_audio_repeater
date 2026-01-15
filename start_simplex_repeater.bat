@echo off
chcp 65001 > nul
title Simplex Audio Repeater - Starter
color 0A

echo ================================================================================
echo                       Simplex Audio Repeater - Starter
echo ================================================================================
echo.

REM ============================================================================
REM Schritt 1: Prüfen ob Python installiert ist
REM ============================================================================
echo [1/4] Überprüfe Python Installation...
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Python ist nicht installiert oder nicht im PATH!
    echo.
    echo Python wird für dieses Programm benötigt.
    echo.
    echo Sie haben folgende Optionen:
    echo.
    echo Option 1: Automatische Installation ^(empfohlen^)
    echo   - Python wird automatisch heruntergeladen und installiert
    echo   - Benötigt Administrator-Rechte
    echo.
    echo Option 2: Manuelle Installation
    echo   - Besuchen Sie: https://www.python.org/downloads/
    echo   - Laden Sie Python 3.8 oder höher herunter
    echo   - WICHTIG: Aktivieren Sie "Add Python to PATH" während der Installation!
    echo.
    
    set /p choice="Möchten Sie Python automatisch installieren? (J/N): "
    if /i "%choice%"=="J" goto :install_python
    if /i "%choice%"=="Y" goto :install_python
    
    echo.
    echo Installation abgebrochen. Bitte installieren Sie Python manuell und
    echo starten Sie dieses Skript erneut.
    echo.
    pause
    exit /b 1
)

python --version
echo [OK] Python ist installiert!
echo.

REM ============================================================================
REM Schritt 2: Python-Version prüfen
REM ============================================================================
echo [2/4] Prüfe Python-Version...
echo.

python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNUNG] Python 3.8 oder höher wird empfohlen!
    echo Aktuelle Version:
    python --version
    echo.
    echo Das Programm könnte trotzdem funktionieren, aber es wird empfohlen,
    echo Python zu aktualisieren: https://www.python.org/downloads/
    echo.
    set /p continue="Trotzdem fortfahren? (J/N): "
    if /i not "%continue%"=="J" if /i not "%continue%"=="Y" exit /b 1
) else (
    echo [OK] Python-Version ist kompatibel!
)
echo.

REM ============================================================================
REM Schritt 3: Virtuelle Umgebung erstellen oder aktivieren
REM ============================================================================
echo [3/4] Richte virtuelle Umgebung ein...
echo.

if not exist "venv" (
    echo Erstelle virtuelle Umgebung...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [FEHLER] Konnte virtuelle Umgebung nicht erstellen!
        echo Versuche ohne virtuelle Umgebung fortzufahren...
        goto :skip_venv
    )
    echo [OK] Virtuelle Umgebung erstellt!
) else (
    echo [OK] Virtuelle Umgebung existiert bereits!
)

echo Aktiviere virtuelle Umgebung...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [WARNUNG] Konnte virtuelle Umgebung nicht aktivieren!
    echo Fahre ohne virtuelle Umgebung fort...
    goto :skip_venv
)
echo [OK] Virtuelle Umgebung aktiviert!
echo.

:skip_venv

REM ============================================================================
REM Schritt 4: Abhängigkeiten installieren
REM ============================================================================
echo [4/4] Installiere/Aktualisiere Abhängigkeiten...
echo.

if not exist "requirements.txt" (
    echo [FEHLER] requirements.txt nicht gefunden!
    echo.
    pause
    exit /b 1
)

echo Installiere pip-Pakete aus requirements.txt...
echo.
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [FEHLER] Installation der Abhängigkeiten fehlgeschlagen!
    echo.
    echo Mögliche Lösungen:
    echo 1. Stellen Sie sicher, dass Sie eine Internetverbindung haben
    echo 2. Führen Sie das Skript als Administrator aus
    echo 3. Installieren Sie PyAudio manuell mit:
    echo    pip install pipwin
    echo    pipwin install pyaudio
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] Alle Abhängigkeiten installiert!
echo.

REM ============================================================================
REM Programm starten
REM ============================================================================
echo ================================================================================
echo                        Starte Simplex Audio Repeater...
echo ================================================================================
echo.
echo Hinweis: Schließen Sie dieses Fenster NICHT, während das Programm läuft!
echo.

python simplex_repeater.py
if %errorlevel% neq 0 (
    echo.
    echo [FEHLER] Das Programm wurde mit einem Fehler beendet (Code: %errorlevel%)!
    echo.
    pause
    exit /b %errorlevel%
)

echo.
echo ================================================================================
echo                        Programm wurde beendet
echo ================================================================================
echo.
pause
exit /b 0

REM ============================================================================
REM Python Installation
REM ============================================================================
:install_python
echo.
echo ================================================================================
echo                       Python Installation wird gestartet...
echo ================================================================================
echo.

REM Erstelle temporären Download-Ordner
set "TEMP_DIR=%TEMP%\python_installer"
if not exist "%TEMP_DIR%" mkdir "%TEMP_DIR%"

REM Python-Download-URL (Python 3.11.7 - Stabile Version)
set "PYTHON_VERSION=3.11.7"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-amd64.exe"
set "INSTALLER_PATH=%TEMP_DIR%\python_installer.exe"

echo Lade Python %PYTHON_VERSION% herunter...
echo Dies kann einige Minuten dauern...
echo.

REM Prüfe ob PowerShell verfügbar ist
powershell -Command "Get-Command Invoke-WebRequest" >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] PowerShell ist nicht verfügbar!
    echo Bitte installieren Sie Python manuell von: %PYTHON_URL%
    echo.
    pause
    exit /b 1
)

REM Download mit PowerShell
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%INSTALLER_PATH%'}"
if %errorlevel% neq 0 (
    echo [FEHLER] Download fehlgeschlagen!
    echo.
    echo Bitte laden Sie Python manuell herunter:
    echo %PYTHON_URL%
    echo.
    pause
    exit /b 1
)

echo [OK] Download abgeschlossen!
echo.
echo Starte Python-Installation...
echo.
echo WICHTIG: Während der Installation werden Sie möglicherweise nach
echo Administrator-Rechten gefragt. Bitte bestätigen Sie diese Anfrage!
echo.
pause

REM Python installieren mit automatischen Optionen
echo Installiere Python %PYTHON_VERSION%...
echo.

"%INSTALLER_PATH%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_doc=0 Include_launcher=1
if %errorlevel% neq 0 (
    echo.
    echo [FEHLER] Installation fehlgeschlagen!
    echo.
    echo Versuchen Sie eine manuelle Installation:
    echo 1. Öffnen Sie: %INSTALLER_PATH%
    echo 2. Aktivieren Sie "Add Python to PATH"
    echo 3. Klicken Sie auf "Install Now"
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] Python wurde erfolgreich installiert!
echo.
echo WICHTIG: Sie müssen diese Eingabeaufforderung SCHLIESSEN und neu öffnen,
echo damit Python im PATH verfügbar ist!
echo.
echo Führen Sie danach diese Datei erneut aus.
echo.

REM Aufräumen
del "%INSTALLER_PATH%" >nul 2>&1
rmdir "%TEMP_DIR%" >nul 2>&1

pause
exit /b 0
