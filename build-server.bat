@echo off
echo ===============================================
echo      Reading Diary Server & GUI Build
echo ===============================================
echo.

:: Go zum Hauptverzeichnis wechseln
cd /d "%~dp0"

echo [1/3] Überprüfe Go-Installation...
go version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Go ist nicht installiert oder nicht im PATH!
    echo Bitte installieren Sie Go von https://golang.org/dl/
    pause
    exit /b 1
)

echo [2/3] Lade Abhängigkeiten...
go mod tidy
if errorlevel 1 (
    echo FEHLER: Konnte Abhängigkeiten nicht laden!
    pause
    exit /b 1
)

echo [3/3] Kompiliere Server mit GUI (ohne CMD-Fenster)...
if not exist "bin" mkdir bin
go build -ldflags="-H windowsgui" -o bin\reading-diary-server.exe main.go
if errorlevel 1 (
    echo FEHLER: Kompilierung fehlgeschlagen!
    pause
    exit /b 1
)

echo.
echo ✓ Reading Diary Server + GUI erfolgreich kompiliert!
echo ✓ Ausführbare Datei: bin\reading-diary-server.exe
echo.
echo Funktionen:
echo   - GUI-Anwendung mit integrierter Server-Kontrolle
echo   - Vollständiges Logging in der GUI
echo   - Web-Interface unter http://localhost:7443
echo   - Standard-Passwort: admin123
echo.
echo Starten:
echo   GUI-Modus:    bin\reading-diary-server.exe
echo   Server-Only:  bin\reading-diary-server.exe [PORT] [PASSWORT]
echo.
pause
