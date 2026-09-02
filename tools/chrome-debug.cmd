@echo off
rem ---------------------------------------------------------------------------
rem OPTIONAL. Nur noetig fuer bessere Zuverlaessigkeit oder fuer PRIVATE
rem Instagram-Profile, denen du folgst.
rem
rem Ohne diese Datei startet social_holen.py bei Bedarf SELBST einen headless-
rem Chrome (nicht angemeldet) -- das reicht fuer oeffentliche Profile, Instagram
rem kann den ausgeloggten Browser aber zeitweise abblocken (429 / Login-Wand).
rem
rem Startest du hingegen DIESEN Chrome und meldest dich in dem Fenster einmal
rem bei instagram.com an, nimmt social_holen ihn statt des headless -- er sieht
rem auch private Profile und wird seltener abgeblockt. Login-Cookie bleibt im
rem Profilordner (Wochen bis Monate), danach neu anmelden.
rem
rem Vom normalen Chrome getrennt (eigener --user-data-dir): laeuft daneben, deine
rem Sitzung bleibt unberuehrt. Eigener --user-data-dir ist ausserdem Pflicht --
rem Chrome >= 136 laesst den Debug-Port am Standardprofil nicht mehr zu.
rem ---------------------------------------------------------------------------
setlocal

set "PROFIL=%LOCALAPPDATA%\kulturfein-chrome"

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
    echo chrome.exe nicht gefunden. Pfad in dieser Datei anpassen.
    exit /b 1
)

echo Chrome:  "%CHROME%"
echo Profil:  "%PROFIL%"
echo Port:    9222
echo.
echo Fenster offen lassen, solange domain_lauf / termine_aus_domain laufen soll.
echo.

start "" "%CHROME%" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%PROFIL%" ^
    --no-first-run ^
    --no-default-browser-check ^
    https://www.instagram.com/
