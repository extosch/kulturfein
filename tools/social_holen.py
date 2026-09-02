#!/usr/bin/env python3
"""Social-Profile ueber einen ferngesteuerten Chrome lesen. Optionales Modul.

termine_aus_domain.py importiert dieses Modul in try/except. Fehlt es (Einzeldatei
woandershin kopiert) oder fehlt pychrome, bleibt alles beim requests-Pfad.

WARUM UEBERHAUPT EIN BROWSER. instagram.com laedt die Post-Texte erst per
JavaScript/XHR nach -- der requests+BeautifulSoup-Pfad von termine_aus_domain.py
bekommt nur rund 54 Zeichen Titel. Ein echter Browser fuehrt das JavaScript aus,
auch ausgeloggt. Der Login ist NICHT der Knackpunkt, das JavaScript ist es.

ZWEI BETRIEBSARTEN, hole() waehlt selbst:

  1. Laeuft schon ein Chrome auf --remote-debugging-port (tools/chrome-debug.cmd,
     einmal von Hand bei Instagram angemeldet), wird DER genommen -- zuverlaessiger
     und sieht auch private Profile, denen du folgst.
  2. Sonst startet hole() SELBST einen headless-Chrome mit eigenem Profilordner
     (AUTO_PROFIL, nicht angemeldet), macht seine Arbeit und beendet ihn wieder.
     Kein Fenster, kein Setup. Reicht fuer oeffentliche Profile; Instagram kann
     den ausgeloggten Browser aber zeitweise abblocken (429 / Login-Wand).

Der selbst gestartete Chrome laeuft neben deinem normalen Chrome -- eigener
--user-data-dir, eigener Prozess, deine Sitzung bleibt unberuehrt. Beendet wird
nur der selbst gestartete, per PID, nie ein fremder.

Kein Chrome/Edge auf der Maschine und keiner auf dem Port -> BrowserNichtErreichbar.

    from social_holen import ist_social, hole, BrowserNichtErreichbar
    text, startadresse, gelesen = hole("instagram.com/foo/", heute, 30000, 9222, print)

Rueckgabe ist formgleich mit termine_aus_domain.sammle_seiten():
(gesamttext, startadresse, [(adresse, zeichen), ...]) -- so laeuft alles danach
(claude_fragen, nachpruefen, verschmelze, domain_log.json) unveraendert weiter.
"""
import datetime as dt
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlparse

try:
    import pychrome
except ImportError:                     # pychrome nicht installiert -> Social aus
    pychrome = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


# pychrome 0.2.4 faengt in seinem Empfangs-Thread WebSocket-, aber keine
# JSON-Fehler ab: schickt Chrome ein leeres Frame, wirft json.loads('') einen
# JSONDecodeError, der Thread stirbt mit Traceback auf stderr. Der Haupt-Flow
# ist davon unberuehrt (alle Antworten kamen schon an). Nur diesen einen Fall
# still schlucken, alles andere durchreichen.
_alter_excepthook = threading.excepthook

def _leiser_thread_excepthook(args):
    if (type(args.exc_value).__name__ == "JSONDecodeError"
            and args.thread is not None and "_recv_loop" in args.thread.name):
        return
    _alter_excepthook(args)

threading.excepthook = _leiser_thread_excepthook


NACHLAUF_S = 3.0        # fester Zusatz nach readyState=complete fuer den XHR-Schub
SEITEN_TIMEOUT_S = 20   # Obergrenze je Navigation
MAX_PERMALINKS = 6      # so viele Rasterlinks einsammeln, ...
POSTS_VORGABE = 4       # ... dann die neuesten N nach Datum behalten
PORT_WARTEN_S = 15      # so lange auf den Debug-Port des selbst gestarteten Chrome warten

# Eigener Profilordner fuer den selbst gestarteten headless-Chrome. BEWUSST ein
# anderer als der von chrome-debug.cmd (kulturfein-chrome): so kollidieren
# der angemeldete Von-Hand-Chrome und der anonyme Automatik-Chrome nie.
AUTO_PROFIL = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "kulturfein-chrome-auto")

# Wo Chrome/Edge auf Windows typischerweise liegt. Erster Treffer gewinnt.
_PF = os.environ.get("PROGRAMFILES", r"C:\Program Files")
_PFX = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
_LA = os.environ.get("LOCALAPPDATA", "")
CHROME_KANDIDATEN = [
    os.path.join(_PF, r"Google\Chrome\Application\chrome.exe"),
    os.path.join(_PFX, r"Google\Chrome\Application\chrome.exe"),
    os.path.join(_LA, r"Google\Chrome\Application\chrome.exe"),
    os.path.join(_PF, r"Microsoft\Edge\Application\msedge.exe"),
    os.path.join(_PFX, r"Microsoft\Edge\Application\msedge.exe"),
]


class BrowserNichtErreichbar(Exception):
    """Kein Chrome erreichbar: keiner auf dem Debug-Port, keiner startbar."""


def _host(ziel):
    """'instagram.com/foo/' oder volle URL -> 'instagram.com' (ohne www.)."""
    roh = ziel if ziel.startswith("http") else "https://" + ziel
    netloc = urlparse(roh).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def ist_social(ziel):
    """Gehoert das Ziel zu einem Host, den nur ein angemeldeter Browser sieht?"""
    return _host(ziel) in SOCIAL_HOSTS


# ------------------------------------------------------------- CDP-Mechanik

class _Tab:
    """Ein Chrome-Tab, ueber CDP ferngesteuert. Fuer alle Navigationen eines
    Aufrufs wiederverwendet, am Ende geschlossen."""

    def __init__(self, browser):
        self.browser = browser
        self.tab = browser.new_tab()
        self.tab.start()
        self.tab.Page.enable()

    def besuche(self, url):
        """Navigieren, auf readyState=complete warten, dann fester Nachlauf."""
        self.tab.Page.navigate(url=url, _timeout=SEITEN_TIMEOUT_S)
        self.tab.wait(1.0)
        ende = time.time() + SEITEN_TIMEOUT_S
        while time.time() < ende:
            if self.js("document.readyState") == "complete":
                break
            self.tab.wait(0.5)
        self.tab.wait(NACHLAUF_S)

    def js(self, ausdruck):
        """Ausdruck im Seitenkontext auswerten -> Python-Wert (oder None)."""
        try:
            antwort = self.tab.Runtime.evaluate(
                expression=ausdruck, returnByValue=True, _timeout=10)
        except Exception:
            return None
        return antwort.get("result", {}).get("value")

    def close(self):
        try:
            self.tab.stop()
        finally:
            self.browser.close_tab(self.tab)


def _port_offen(port):
    """Antwortet auf 127.0.0.1:<port> ein DevTools-Endpunkt?"""
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=2).read()
        return True
    except Exception:
        return False


def _chrome_pfad():
    """Erster existierender Chrome/Edge aus CHROME_KANDIDATEN, sonst None."""
    for pfad in CHROME_KANDIDATEN:
        if pfad and os.path.exists(pfad):
            return pfad
    return None


def _starte_headless(port, melde):
    """headless-Chrome mit eigenem Profil starten, auf den Port warten -> Popen.

    Wirft BrowserNichtErreichbar, wenn kein Chrome/Edge gefunden wird oder der
    Port nicht hochkommt.
    """
    pfad = _chrome_pfad()
    if not pfad:
        raise BrowserNichtErreichbar(
            f"kein Chrome/Edge gefunden und keiner auf 127.0.0.1:{port} -- "
            f"tools/chrome-debug.cmd starten oder Chrome installieren")
    os.makedirs(AUTO_PROFIL, exist_ok=True)
    befehl = [pfad, "--headless=new", f"--remote-debugging-port={port}",
              f"--user-data-dir={AUTO_PROFIL}", "--no-first-run",
              "--no-default-browser-check", "--disable-gpu",
              "--disable-extensions", "about:blank"]
    proc = subprocess.Popen(
        befehl, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ende = time.time() + PORT_WARTEN_S
    while time.time() < ende:
        if _port_offen(port):
            melde(f"  headless-Chrome gestartet (PID {proc.pid})")
            return proc
        if proc.poll() is not None:            # sofort wieder weg
            break
        time.sleep(0.5)
    _beende(proc)
    raise BrowserNichtErreichbar(
        f"headless-Chrome kam binnen {PORT_WARTEN_S}s nicht auf :{port}")


def _beende(proc):
    """Nur den selbst gestarteten Prozess beenden -- per PID, mitsamt Kindern."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def hole(ziel, heute, budget, port, melde, posts=POSTS_VORGABE):
    """Social-Profil -> (gesamttext, startadresse, [(adresse, zeichen), ...]).

    Nimmt einen Chrome auf 127.0.0.1:<port>, wenn einer laeuft; sonst startet es
    selbst einen headless (und beendet ihn am Ende wieder). Wirft
    BrowserNichtErreichbar, wenn pychrome fehlt oder gar kein Chrome zu haben ist.
    """
    if pychrome is None:
        raise BrowserNichtErreichbar("pychrome ist nicht installiert "
                                     "(pip install pychrome)")
    handler = SOCIAL_HOSTS.get(_host(ziel))
    if handler is None:
        raise BrowserNichtErreichbar(f"kein Social-Handler fuer {_host(ziel)}")

    eigener = None
    if _port_offen(port):
        melde(f"  Chrome auf :{port} gefunden, docke an")
    else:
        eigener = _starte_headless(port, melde)     # wirft, wenn keiner startbar

    try:
        browser = pychrome.Browser(url=f"http://127.0.0.1:{port}")
        browser.list_tab()                          # Verbindung wirklich da?
        return handler(browser, ziel, heute, budget, melde, posts)
    except BrowserNichtErreichbar:
        raise
    except Exception as fehler:
        raise BrowserNichtErreichbar(
            f"Chrome auf 127.0.0.1:{port} antwortet nicht "
            f"({type(fehler).__name__})") from fehler
    finally:
        _beende(eigener)                            # nie einen fremden Chrome


# ------------------------------------------------------------------ Instagram

def _instagram(browser, ziel, heute, budget, melde, posts):
    roh = ziel if ziel.startswith("http") else "https://" + ziel
    nutzer = urlparse(roh).path.strip("/").split("/")[0]
    profil = f"https://www.instagram.com/{nutzer}/"

    tab = _Tab(browser)
    try:
        tab.besuche(profil)
        bio = (tab.js("document.body.innerText") or "").strip()

        roh_links = tab.js(
            "Array.from(document.querySelectorAll("
            "'a[href*=\"/p/\"],a[href*=\"/reel/\"]')).map(a => a.href)") or []
        permalinks = _permalinks(roh_links, MAX_PERMALINKS)
        if not permalinks:
            # Kein einziger Beitragslink sichtbar: fast immer heisst das nicht
            # eingeloggt (oder privates Profil, oder Instagram hat das Markup
            # geaendert). Bio kommt trotzdem zurueck, aber ohne Termine.
            melde(f"  Instagram {nutzer}: keine Beitraege sichtbar -- "
                  f"chrome-debug.cmd bei Instagram anmelden (oder privates Profil)")

        beitraege = []
        for url in permalinks:
            tab.besuche(url)
            text = (tab.js("document.querySelector('main') && "
                           "document.querySelector('main').innerText") or "").strip()
            iso = tab.js("document.querySelector('time') && "
                         "document.querySelector('time').getAttribute('datetime')")
            beitraege.append(((iso or ""), url, text))
    finally:
        tab.close()

    # Neueste zuerst -- ISO-Zeitstempel sortieren sich lexikografisch richtig,
    # datumlose ans Ende. Faengt angepinnte Alt-Posts ab, die im Raster oben
    # stehen (bei manchen Profilen 20+ Wochen alt).
    beitraege.sort(key=lambda b: b[0] or "0000", reverse=True)
    beitraege = beitraege[:posts]
    melde(f"  Instagram {nutzer}: {len(bio)} Z Bio, {len(permalinks)} Permalinks, "
          f"{len(beitraege)} Beitraege nach Datum")

    # Abschnitte bauen, Zeichenbudget mitzaehlen -- wie sammle_seiten mit 'uebrig'.
    kopf = f"--- {profil} ---\n"
    rumpf = bio[:max(0, budget - len(kopf))]
    abschnitte = [kopf + rumpf]
    gelesen = [(profil, len(rumpf))]
    uebrig = budget - len(abschnitte[0])

    for iso, url, text in beitraege:
        if uebrig <= 0:
            melde(f"  {url}  uebersprungen (Zeichenbudget erschoepft)")
            continue
        marke = f"--- {url} ---\n"
        wann = f"[{iso[:10]}] " if iso else ""
        stueck = (wann + text)[:max(0, uebrig - len(marke))]
        abschnitte.append(marke + stueck)
        gelesen.append((url, len(stueck)))
        uebrig -= len(marke) + len(stueck)
        melde(f"  {url}  {len(stueck)} Z  {iso[:10] if iso else '?'}")

    return "\n\n".join(abschnitte), profil, gelesen


def _permalinks(rohe, grenze):
    """href-Liste -> bis zu 'grenze' eindeutige, normalisierte Post-Adressen."""
    gesehen, sauber = set(), []
    for href in rohe:
        treffer = re.search(r"/(p|reel)/([^/?#]+)", href or "")
        if not treffer:
            continue
        norm = f"https://www.instagram.com/{treffer.group(1)}/{treffer.group(2)}/"
        if norm not in gesehen:
            gesehen.add(norm)
            sauber.append(norm)
        if len(sauber) >= grenze:
            break
    return sauber


# Host -> Handler. facebook.com spaeter: ein Eintrag + eine _facebook-Funktion.
SOCIAL_HOSTS = {"instagram.com": _instagram}


if __name__ == "__main__":
    ziel = sys.argv[1] if len(sys.argv) > 1 else "instagram.com/instagram/"
    text, quelle, gelesen = hole(ziel, dt.date.today(), 30000, 9222, print)
    print("=" * 72)
    print("QUELLE:", quelle)
    for adresse, n in gelesen:
        print(f"  {n:6d} Z  {adresse}")
    print("=" * 72)
    print(text[:4000])
