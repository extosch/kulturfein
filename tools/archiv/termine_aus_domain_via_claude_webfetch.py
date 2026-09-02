#!/usr/bin/env python3
"""Modell-Only-Variante: Domain rein, Claude sucht die Termine SELBST.

Gegenstueck zu termine_aus_domain.py. Dort macht Python alles: Abruf,
HTML->Text, Unterseitenauswahl per Punkteschema, lokale Belegpruefung. Hier
macht Python NICHTS davon -- das Modell bekommt nur die Domain und das
Werkzeug WebFetch, ruft selbst ab, folgt selbst Links, entscheidet selbst,
was eine Terminseite ist.

Gemessen am 30.08.2026, Klavierdepot Freiburg, gleicher Fall wie in
termine_aus_domain.py:

    termine_aus_domain.py (Heuristik)     0,0062 USD
    dieses Skript (WebFetch)              0,028  USD

Rund 4,5x teurer -- das ist der reale Preis eines tatsaechlichen Abrufs samt
Cache-Erzeugung fuer den gelesenen Text, nicht nur die Werkzeugbeschreibung
(die allein kostet nur rund 1.000 Token Aufpreis, gemessen ohne echten
Abruf). Alle vier bekannten Termine wurden trotzdem korrekt gefunden, mit
sauberem Werkzeug-Trace:

    tool_use: WebFetch {url: 'https://www.petra-gack.de/klavierdepot', ...}
    tool_use: StructuredOutput {termine: [4 korrekte Eintraege]}

DENKEN BLEIBT AN. Im Gegenstueck-Skript senkt MAX_THINKING_TOKENS=0 die
Kosten UND verdoppelt den Trefferwert -- aber das war fuers Abschreiben aus
fertigem Text gemessen. Navigieren (welche Unterseite ist relevant, wann
reicht die Startseite) ist eine Denkaufgabe; --kein-denken steht als
Schalter fuer den direkten Vergleich zur Verfuegung, ist aber nicht Default.

KEINE BELEGPRUEFUNG. Ohne lokal abgerufenen Text gibt es nichts, wogegen
Datum und Titel geprueft werden koennten -- das ist kein Bug, sondern der
Punkt der Uebung. Das Modell berichtet stattdessen selbst im Feld
'besuchte_seiten', welche Adressen es abgerufen hat. Das ist Transparenz,
keine Pruefung.

BEKANNTE GRENZEN, unveraendert gegenueber dem Gegenstueck:

    jazzhaus.de     Inhalt wird per JavaScript nachgeladen. WebFetch
                    rendert ebenfalls kein JavaScript -- derselbe Fall
                    scheitert hier genauso.
    schopf2.de      162-Byte-Seite mit Meta-Refresh-Weiterleitung auf
                    kreativpioniere-freiburg.de. WebFetch folgt ihr NICHT
                    und antwortet ehrlich mit einer Fehlermeldung statt
                    einem stillen Nullergebnis wie im Gegenstueck.

STDIN. Der claude-Aufruf braucht keinen Seitentext mehr als Eingabe --
wird kein input="" gesetzt, wartet der Prozess 3 Sekunden auf stdin und
meldet eine Warnung, bevor er ohne Eingabe weitermacht. Deshalb wird
input="" hier immer explizit gesetzt.

GEPARKT AM 30.08.2026. Der erste Messwert oben (0,028 USD, 4 Treffer) kam aus
einem Kalibrierungslauf mit vorgegebener Ziel-URL. Der erste echte Lauf mit
nur der Domain (also der eigentliche Anwendungsfall) sah anders aus, gleicher
Fall, gleiche Domain:

    Skript 1 (Heuristik)     1 Seite     4 Termine     0,0062 USD
    dieses Skript (Domain)   5 Seiten    1 Termin      0,0753 USD

Das Modell hat die echte Weiterleitung gefunden, dann aber drei plausibel
klingende Unterseiten ERFUNDEN (/programm, /veranstaltungen, /termine --
keine davon existiert; das Klavierdepot ist eine einzige Seite ohne
Unterseiten, siehe Skript 1: "kein Link trifft ein Stichwort"). Das ist kein
Zufallstreffer, sondern strukturell: ohne die Seite vorher gesehen zu haben,
kann das Modell nur raten, welche Unterseiten existieren koennten. Skript 1s
Heuristik arbeitet dagegen ausschliesslich auf tatsaechlich im HTML
vorhandenen Links -- sie rät nie, sie liest nur, was da ist.

Konsequenz: Skript 1 bleibt der Hauptweg, Claude wird dort weiterhin nur fuer
die Extraktion aus bereits gesammeltem Text eingesetzt, nicht fuer die
Navigation. Diese Datei bleibt liegen (Wrapper, Messwerte, Diagnose sind
selbst ein Befund), wird aber nicht weiter poliert -- der naheliegende
Gegen-Fix (Prompt scharfen: "nur echten Links folgen, keine URLs raten")
waere moeglich, ist aber genau die Art Nacharbeit, die die Rueckkehr zu
Skript 1 gerade vermeiden soll.

    termine2 klavierdepot-freiburg.de           # ueber .local/bin/termine2
    python termine_aus_domain_via_claude_webfetch.py foo.de
    termine2 foo.de --show-prompt               # den Auftrag an claude zeigen
    termine2 foo.de --verbose                   # Werkzeug-Trace auf stderr
    termine2 foo.de --kein-denken               # Vergleichswert zu Skript 1
    termine2 foo.de --websearch                 # zusaetzlich WebSearch erlauben
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ZEITLIMIT = 480        # Sekunden je claude-Aufruf -- mehrere Werkzeugrunden statt eines
                       # einzelnen Completion-Calls, daher hoeher als in Skript 1

# Leerer Ordner ausserhalb des Projekts, eigener Name als das Gegenstueck-Skript
# benutzt -- damit beide Skripte unabhaengig voneinander laufen koennen.
ARBEITSORDNER = os.path.join(tempfile.gettempdir(), "kulturfein_webfetch_cwd")

# Nur bei --kein-denken gesetzt (siehe Kopf: Navigieren ist eine Denkaufgabe).
OHNE_DENKEN = {"MAX_THINKING_TOKENS": "0"}

# Geschlossene Liste, identisch zu termine_aus_domain.py. Umlaute umschrieben,
# weil der Auftrag als Kommandozeilenargument uebergeben wird.
GENRES = ["Tanz", "Theater", "Vortrag", "Religioese Veranstaltung", "Vernissage",
          "Konzert", "Lesung", "Workshop", "Sonstiges"]

SYSTEMPROMPT = ("Du recherchierst mit dem Werkzeug WebFetch selbststaendig auf "
                "Veranstalter-Websites und gibst gefundene Termine als JSON "
                "zurueck. Antworte ausschliesslich mit JSON, ohne Vorrede und "
                "ohne Code-Zaun.")

SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "termine": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "datum": {"type": "string"},
                    "uhrzeit": {"type": "string"},
                    "titel": {"type": "string"},
                    "ort": {"type": "string"},
                    "beschreibung": {"type": "string"},
                    "genre": {"type": "string", "enum": GENRES},
                },
                "required": ["datum", "titel", "genre"],
            },
        },
        "besuchte_seiten": {
            # Reine Transparenz -- keine Pruefgrundlage, siehe Kopf.
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["termine"],
}, ensure_ascii=False)


def auftrag_domain(domain, heute):
    """Der Prompt fuer die Claude-Only-Variante: statt fertigem Text bekommt
    das Modell nur die Domain und den Auftrag, selbst zu recherchieren.

    Die Kernregeln (Datumsformat, Zeitraum-vs-Einzeltermin, "KEINE
    Veranstaltung sind") sind wortgleich aus auftrag() in
    termine_aus_domain.py uebernommen -- sie entstanden aus konkreten
    Fehlfunden (neun Geistervernissagen bei der Stiftung fuer Konkrete
    Kunst) und gelten unveraendert, egal ob ein Python-Skript oder das
    Modell selbst liest. Die Schritte 1-4 ersetzen, was dort Code war
    (hole_startseite(), waehle_unterseiten(), _ist_archiv()) durch dieselben
    Regeln als Anweisung.
    """
    return (
        f"Heute ist der {heute:%d.%m.%Y}. Du hast Zugriff auf das Werkzeug "
        "WebFetch, mit dem du beliebige Webseiten abrufen kannst.\n\n"
        f"Recherchiere auf der Website der Domain {domain} alle "
        "ANGEKUENDIGTEN Veranstaltungen. Gehe so vor:\n\n"
        "1. Rufe zuerst die Startseite ab. Probiere https:// vor http://, "
        "und falls eine Adresse nicht antwortet, probiere sie mit "
        "vorangestelltem 'www.'.\n"
        "2. Pruefe, ob die Startseite selbst schon Termine mit Datum "
        "auflistet. Falls nicht, oder falls sie auf eine eigene Terminseite "
        "verweist, rufe zusaetzlich bis zu vier thematisch passende "
        "Unterseiten ab -- erkennbar an Linktext oder Pfad mit Woertern wie "
        "'Veranstaltungen', 'Termine', 'Konzerte', 'Programm', 'Kalender', "
        "'Spielplan', 'Agenda', 'Spielzeit', 'Ausstellungen', 'Aktuelles', "
        "'Vorschau', 'Events', 'Vernissage', 'Lesung'.\n"
        "3. Rufe NICHT ab: Newsletter-Anmeldung, Impressum, Datenschutz, "
        "Kontakt, Anfahrt, AGB, Spenden, Mitgliedschaft, Presse, oder "
        "Archivseiten vergangener Jahre (z.B. eine Jahresnavigation, deren "
        f"juengstes Jahr vor {heute.year} liegt).\n"
        "4. Rufe insgesamt hoechstens fuenf Seiten ab (Startseite plus vier "
        "Unterseiten).\n\n"
        "Datum als JJJJ-MM-TT, Uhrzeit als HH:MM (leer lassen, wenn keine "
        "angegeben ist), Titel wortgetreu aus dem abgerufenen Text.\n\n"
        "ort (Veranstaltungsort) wortgetreu aus dem abgerufenen Text, leer "
        "lassen, wenn keiner angegeben ist.\n\n"
        "beschreibung ist ein woertliches Kurzzitat aus dem abgerufenen Text "
        "(hoechstens 150 Zeichen), das die Veranstaltung naeher beschreibt "
        "-- kein eigener Satz, keine Zusammenfassung. Nur angeben, wenn ein "
        "passendes Zitat im Text steht, sonst leer lassen.\n\n"
        "genre ist genau einer dieser Werte:\n"
        + " | ".join(GENRES) + "\n\n"
        "Jedes zurueckgegebene Datum muss WORTWOERTLICH auf einer "
        "abgerufenen Seite stehen. Rechne nichts aus. Ein Zeitraum "
        "('13.09.2026 bis 08.11.2026') ist EINE Angabe und keine Reihe von "
        "Einzelterminen -- loese ihn nicht in Wochentage auf. Wiederkehrende "
        "Oeffnungszeiten ('Sonntags von 11:30 bis 16:00 Uhr') sind kein "
        "Termin. Sind fuer dieselbe Veranstaltung mehrere Daten einzeln "
        "genannt, gib jedes davon zurueck.\n\n"
        "KEINE Veranstaltung sind: Nachrichten und Meldungen, Rueckblicke "
        "auf Vergangenes, Ausstellungsdauern, Oeffnungszeiten, "
        "Jahresarchive vergangener Spielzeiten, Pressemitteilungen, "
        "Anfahrtshinweise, Preisangaben.\n\n"
        "Erfinde nichts. Steht kein Termin auf den abgerufenen Seiten, gib "
        "eine leere Liste zurueck. Nenne im Feld 'besuchte_seiten' jede "
        "Adresse, die du tatsaechlich abgerufen hast."
    )


# -------------------------------------------------------------- claude rufen

def _json_herausschneiden(rohtext):
    """Das erste vollstaendige {...} aus einem Text. -> str oder ''

    Trotz --json-schema zaeunt das Modell die Antwort gern mit ```json ein.
    Statt darauf zu vertrauen, wird geschnitten. Unveraendert aus
    termine_aus_domain.py uebernommen.
    """
    anfang = rohtext.find("{")
    if anfang < 0:
        return ""
    tiefe, in_text, geschuetzt = 0, False, False
    for i in range(anfang, len(rohtext)):
        z = rohtext[i]
        if geschuetzt:
            geschuetzt = False
        elif z == "\\":
            geschuetzt = True
        elif z == '"':
            in_text = not in_text
        elif not in_text:
            if z == "{":
                tiefe += 1
            elif z == "}":
                tiefe -= 1
                if tiefe == 0:
                    return rohtext[anfang:i + 1]
    return ""


def _verlauf_zeigen(tool_aufrufe):
    """Der --verbose-Block: welche Werkzeuge hat das Modell tatsaechlich
    aufgerufen, in welcher Reihenfolge. StructuredOutput ist die
    Endausgabe, kein Rechercheschritt, und wird deshalb nicht gezeigt.
    """
    print("WERKZEUGE", file=sys.stderr)
    gezeigt = [(name, eingabe) for name, eingabe in tool_aufrufe
               if name != "StructuredOutput"]
    if not gezeigt:
        print("  (kein Werkzeug aufgerufen)", file=sys.stderr)
        return
    for name, eingabe in gezeigt:
        if name == "WebFetch":
            print(f"  WebFetch    {eingabe.get('url', '?')}", file=sys.stderr)
        elif name == "WebSearch":
            print(f"  WebSearch   {eingabe.get('query', eingabe)}", file=sys.stderr)
        else:
            print(f"  {name}  {eingabe}", file=sys.stderr)


def claude_web_fragen(domain, heute, modell, effort, kein_denken, websearch,
                       zeitlimit, verbose):
    """Der konfektionierte Aufruf, ohne lokalen Seitentext. -> (funde,
    besuchte_seiten, kennzahlen)

    --tools/--allowedTools werden identisch gesetzt: --tools waehlt, welche
    Werkzeuge dem Modell BEKANNT sind, --allowedTools, dass es sie OHNE
    Rueckfrage nutzen darf. Nur beides zusammen macht das Skript unabhaengig
    von einer zufaellig vorhandenen globalen Werkzeug-Freigabe.
    """
    os.makedirs(ARBEITSORDNER, exist_ok=True)
    werkzeuge = ["WebFetch"] + (["WebSearch"] if websearch else [])
    ausgabeformat = "stream-json" if verbose else "json"

    befehl = ["claude", "-p", auftrag_domain(domain, heute),
              "--system-prompt", SYSTEMPROMPT,
              "--output-format", ausgabeformat,
              "--json-schema", SCHEMA,
              "--model", modell,
              "--tools", *werkzeuge,
              "--allowedTools", *werkzeuge,
              "--no-session-persistence"]
    if verbose:
        befehl.append("--verbose")   # noetig, damit stream-json die tool_use-Bloecke traegt
    if effort:
        befehl += ["--effort", effort]

    env = dict(os.environ, **(OHNE_DENKEN if kein_denken else {}))
    try:
        lauf = subprocess.run(befehl, input="", capture_output=True, text=True,
                              encoding="utf-8", timeout=zeitlimit,
                              cwd=ARBEITSORDNER,          # weg vom Projektordner
                              env=env)
    except FileNotFoundError:
        print("FEHLER: 'claude' ist nicht im Pfad. Ohne Claude Code laeuft "
              "dieses Werkzeug nicht.", file=sys.stderr)
        return None, [], {}
    except subprocess.TimeoutExpired:
        print(f"FEHLER: keine Antwort binnen {zeitlimit} s.", file=sys.stderr)
        return None, [], {}

    if lauf.returncode != 0:
        print(f"FEHLER: claude endete mit {lauf.returncode}\n"
              f"{(lauf.stderr or '')[:400]}", file=sys.stderr)
        return None, [], {}

    if verbose:
        antwort, tool_aufrufe = {}, []
        for zeile in lauf.stdout.splitlines():
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                ereignis = json.loads(zeile)
            except json.JSONDecodeError:
                continue
            if ereignis.get("type") == "assistant":
                for block in ereignis.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        tool_aufrufe.append((block.get("name"), block.get("input", {})))
            elif ereignis.get("type") == "result":
                antwort = ereignis
        _verlauf_zeigen(tool_aufrufe)
    else:
        try:
            antwort = json.loads(lauf.stdout)
        except json.JSONDecodeError:
            print(f"FEHLER: Antwort ist kein JSON:\n{lauf.stdout[:300]}", file=sys.stderr)
            return None, [], {}

    inhalt = antwort.get("structured_output") or {}
    if not inhalt and antwort.get("result"):
        geschnitten = _json_herausschneiden(antwort["result"])
        try:
            inhalt = json.loads(geschnitten) if geschnitten else {}
        except json.JSONDecodeError:
            inhalt = {}

    nutzung = antwort.get("usage", {})
    kennzahlen = {
        "kosten": round(antwort.get("total_cost_usd", 0.0), 6),
        "ein": nutzung.get("input_tokens", 0)
              + nutzung.get("cache_creation_input_tokens", 0)
              + nutzung.get("cache_read_input_tokens", 0),
        "aus": nutzung.get("output_tokens", 0),
    }
    return inhalt.get("termine", []), inhalt.get("besuchte_seiten", []), kennzahlen


# ------------------------------------------------------------------ Saeubern

def saeubere(funde):
    """Schema-Hygiene ohne Textabgleich. -> (gute, verworfene)

    Es gibt keinen lokalen Text mehr, gegen den Datum oder Titel geprueft
    werden koennten (siehe Kopf) -- das Modell hat selbst gelesen. Was
    bleibt: ISO-Datum muss parsen, Titel darf nicht leer sein, Genre wird
    auf die geschlossene Liste normalisiert. Ein unbekanntes Genre wird auf
    'Sonstiges' gesetzt statt verworfen, wie im Gegenstueck-Skript.
    """
    gut, verworfen = [], []
    for fund in funde:
        titel = fund.get("titel") or ""
        try:
            dt.date.fromisoformat(fund.get("datum", ""))
        except (ValueError, TypeError):
            verworfen.append((fund, "Datum unlesbar"))
            continue
        if not titel:
            verworfen.append((fund, "kein Titel"))
            continue
        genre = next((g for g in GENRES
                      if g.lower() == (fund.get("genre") or "").strip().lower()),
                     "Sonstiges")
        # ort/beschreibung durchgereicht wie uhrzeit -- ohne lokalen Text
        # gibt es hier nichts, wogegen sie geprueft werden koennten.
        gut.append({"datum": fund["datum"], "uhrzeit": fund.get("uhrzeit") or "",
                    "titel": titel, "ort": fund.get("ort") or "",
                    "beschreibung": (fund.get("beschreibung") or "")[:150],
                    "genre": genre})
    return sorted(gut, key=lambda t: (t["datum"], t["uhrzeit"])), verworfen


# ------------------------------------------------------------------- Darstellen

def als_text(ergebnis, heute):
    """Lesbare Fassung eines Ergebnisses. -> str

    Eigene, schlankere Fassung als im Gegenstueck: Felder wie 'zeichen' oder
    Zeichenzahlen je Seite gibt es hier nicht, 'besuchte_seiten' tritt an
    ihre Stelle -- als Bericht des Modells, nicht als Pruefgrundlage.
    """
    zeilen = [f"# {ergebnis['ziel']}"]
    if "fehler" in ergebnis:
        zeilen.append(f"  {ergebnis['fehler']}")
        return "\n".join(zeilen)

    besuchte = ergebnis.get("besuchte_seiten", [])
    if besuchte:
        zeilen.append(f"  {len(besuchte)} Seite(n) besucht (laut Modell):")
        for seite in besuchte:
            zeilen.append(f"    + {seite}")
    else:
        zeilen.append("  keine Angabe, welche Seiten besucht wurden")
    zeilen.append("")
    zeilen.append(f"  {ergebnis['gemeldet']} gemeldet, "
                  f"{len(ergebnis['termine'])} uebernommen, "
                  f"{ergebnis['verworfen']} verworfen (Schema-Hygiene, "
                  "keine Belegpruefung)")
    zeilen.append("")
    for t in ergebnis["termine"]:
        kuenftig = "  " if dt.date.fromisoformat(t["datum"]) >= heute else " (vorbei)"
        zeile = (f"  {t['datum']}  {t['uhrzeit'] or '  :  '}  "
                 f"{t['genre']:<24}  {t['titel'][:44]}{kuenftig}")
        if t.get("ort"):
            zeile += f"  @ {t['ort'][:30]}"
        zeilen.append(zeile)
        if t.get("beschreibung"):
            zeilen.append(f"      {t['beschreibung']}")
    for fund, grund in ergebnis.get("_verworfen", []):
        zeilen.append(f"  VERWORFEN  {fund.get('datum', '?')}  "
                      f"{str(fund.get('titel'))[:40]}  — {grund}")
    k = ergebnis["tokens"]
    zeilen.append("")
    zeilen.append(f"  Tokens: {k['ein']} ein / {k['aus']} aus · "
                  f"Kosten: {ergebnis['kosten_usd']:.4f} USD")
    return "\n".join(zeilen)


def ausgeben(ergebnis, heute, als_json, ziel_datei):
    """Format waehlen, Ziel waehlen, ausgeben. Unveraendert aus
    termine_aus_domain.py uebernommen -- das --json/--out-Prinzip ist
    mechanismus-unabhaengig.
    """
    if als_json:
        ergebnis.pop("_verworfen", None)     # Tupel, nicht JSON-faehig
        text = json.dumps(ergebnis, ensure_ascii=False, indent=2)
    else:
        text = als_text(ergebnis, heute)
    if ziel_datei:
        ordner = os.path.dirname(os.path.abspath(ziel_datei))
        os.makedirs(ordner, exist_ok=True)
        with open(ziel_datei, "w", encoding="utf-8") as datei:
            datei.write(text + "\n")
        print(f"-> {ziel_datei}", file=sys.stderr)
    else:
        print(text)


# --------------------------------------------------------------------- Ablauf

def main():
    zerleger = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    zerleger.add_argument("ziel", help="Domain (foo.de) oder vollstaendige Adresse")
    zerleger.add_argument("--json", action="store_true", dest="als_json",
                          help="JSON statt lesbarer Fassung")
    zerleger.add_argument("--out", default="",
                          help="in diese Datei schreiben statt auf stdout")
    zerleger.add_argument("--modell", default="haiku",
                          help="Modell fuer claude -p (Vorgabe: haiku, wie im "
                               "Gegenstueck-Skript -- damit der Vergleich nur "
                               "den Mechanismus testet)")
    zerleger.add_argument("--effort", default="", choices=["", "low", "medium",
                          "high", "xhigh", "max"], help="an claude -p durchgereicht")
    zerleger.add_argument("--kein-denken", action="store_true", dest="kein_denken",
                          help="MAX_THINKING_TOKENS=0 setzen, fuer den Vergleich "
                               "mit termine_aus_domain.py")
    zerleger.add_argument("--websearch", action="store_true",
                          help="zusaetzlich WebSearch erlauben (Rettungsanker, "
                               "falls die Domain allein nicht zur Zielseite fuehrt)")
    zerleger.add_argument("--zeitlimit", type=int, default=ZEITLIMIT,
                          help=f"Sekunden je claude-Aufruf (Vorgabe: {ZEITLIMIT})")
    zerleger.add_argument("--show-prompt", action="store_true", dest="show_prompt",
                          help="den an claude uebergebenen Auftrag ausgeben")
    zerleger.add_argument("--verbose", action="store_true",
                          help="auf stderr zeigen, welche Werkzeuge das Modell "
                               "aufgerufen hat")
    argumente = zerleger.parse_args()

    heute = dt.date.today()
    ergebnis = {"ziel": argumente.ziel, "abgerufen": f"{heute:%Y-%m-%d}", "termine": []}

    def abbrechen(meldung):
        """Fehlerfall: geht denselben Weg wie ein Erfolg, damit --out und
        --json auch dann greifen."""
        ergebnis["fehler"] = meldung
        ausgeben(ergebnis, heute, argumente.als_json, argumente.out)
        return 1

    if argumente.show_prompt:
        auftrag_text = auftrag_domain(argumente.ziel, heute)
        print(f"--- an claude uebergebener Auftrag ({len(auftrag_text)} Zeichen) "
              f"---\n{auftrag_text}\n--- Ende ---", file=sys.stderr)

    funde, besuchte_seiten, k = claude_web_fragen(
        argumente.ziel, heute, argumente.modell, argumente.effort,
        argumente.kein_denken, argumente.websearch, argumente.zeitlimit,
        argumente.verbose)
    if funde is None:
        return abbrechen("claude lieferte keine Antwort")

    gut, verworfen = saeubere(funde)

    ergebnis["quelle"] = besuchte_seiten[0] if besuchte_seiten else ""
    ergebnis["besuchte_seiten"] = besuchte_seiten
    ergebnis["termine"] = gut
    ergebnis["gemeldet"] = len(funde)
    ergebnis["verworfen"] = len(verworfen)
    ergebnis["_verworfen"] = verworfen
    ergebnis["kosten_usd"] = k.get("kosten", 0.0)
    ergebnis["tokens"] = {"ein": k.get("ein", 0), "aus": k.get("aus", 0)}

    ausgeben(ergebnis, heute, argumente.als_json, argumente.out)
    return 0 if gut else 1


if __name__ == "__main__":
    sys.exit(main())
