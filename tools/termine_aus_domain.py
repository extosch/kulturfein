#!/usr/bin/env python3
"""Konfektioniert einen claude-Aufruf: Domain rein, klassifizierte Termine raus.

EIGENSTAENDIG. Keine Projektmodule, nur requests und BeautifulSoup. Die Datei
laesst sich woandershin kopieren und laeuft dort.

Der ganze Zweck ist, EINEN Aufruf sauber zu konfektionieren — Kontext, Modell,
Bedingungen an Lauf und Ausgabe — und sonst nichts. Gemessen am 26.08.2026 gegen
find_dates_in_page.py, das denselben Fall ueber die volle Claude-Code-Umgebung
liest:

    find_dates_in_page.py   12.403 ein /  3.693 aus /  0,0448 USD
    dieses Skript            2.593 ein /    301 aus /  0,0058 USD

Vier Vorkehrungen bewirken das. Eine interaktive Sitzung im Projektordner traegt
43.300 Token mit sich; davon bleiben hier 2.593:

    --tools ""             wirft 23.800 Token Werkzeugbeschreibungen weg
    --system-prompt TEXT   ersetzt 5.200 Token Claude-Code-Systemprompt
    cwd ausserhalb des     verhindert, dass die CLAUDE.md-Dateien des Projekts
    Projektordners         gefunden werden (4.700 Token)
    MAX_THINKING_TOKENS=0  schaltet das Nachdenken ab

Die letzte Zeile ist die ueberraschendste. Gleicher Text, gleicher Auftrag:

    ohne Daempfung         11.049 Denk-Token, 0,0606 USD, 2 Termine
    --effort low            5.248 Denk-Token, 0,0316 USD, 2 Termine
    MAX_THINKING_TOKENS=0       0 Denk-Token, 0,0058 USD, 4 Termine

Das Nachdenken kostet nicht nur das Zehnfache, es halbiert die Trefferquote.
Termine aus einem Text abzuschreiben ist keine Denkaufgabe.

Zwei Schalter, die einander nicht kennen: --json sagt WIE, --out sagt WOHIN.
Daraus ergeben sich vier Faelle, ohne Sonderregel und ohne Negativ-Schalter.

                    stdout                     Datei
    lesbar          termine_aus_domain foo.de             termine_aus_domain foo.de --out x.txt
    JSON            termine_aus_domain foo.de --json      termine_aus_domain foo.de --json --out x.json

    termine_aus_domain klavierdepot-freiburg.de           # ueber .local/bin/termine_aus_domain
    python termine_aus_domain.py foo.de        # oder direkt
    termine_aus_domain foo.de --show-prompt               # Dialog mit claude auf stderr:
                                                          # hin (Auftrag+Schema+Text), zurueck (rohe Antwort)
    termine_aus_domain foo.de --verbose                   # Abruf und Datumsbelege auf stderr
    termine_aus_domain foo.de --modell sonnet

Ohne --out wird nichts geschrieben. Der Fehlerfall nimmt denselben Weg wie der
Erfolg, damit --json und --out auch dann greifen.

MEHRERE SEITEN, EIN AUFRUF. Am 26.08.2026 kam heraus, dass eine Startseite
haeufig nicht genuegt: die Stiftung fuer Konkrete Kunst kuendigt auf der
Startseite nur Ausstellungen an, ihre sechs Konzerte stehen unter
/veranstaltungen/. Seither werden bis zu vier Unterseiten mitgelesen, rein
heuristisch ausgewaehlt (Stichwort im Linktext oder Pfad, Archivjahre raus) und
zu EINEM Modellaufruf zusammengehaengt. Klavierdepot-Links treffen kein
Stichwort — dort bleibt es bei der einen Seite und beim alten Ergebnis.

SOCIAL-HOSTS BRAUCHEN EINEN BROWSER. instagram.com zeigt Ausgeloggten fast
nichts (im Test ueberall HTTP 429) und laedt Beitraege erst per angemeldetem
XHR nach — der requests-Pfad bekaeme nur rund 54 Zeichen Titel. Fuer solche
Hosts uebernimmt das optionale Modul social_holen.py: es steuert einen Chrome
fern, der EINMAL VON HAND bei Instagram angemeldet wurde (tools/chrome-debug.cmd),
und liefert Bio + die neuesten SOCIAL_POSTS Beitraege im selben
'--- <adresse> ---'-Format. Laeuft dieser Chrome nicht, bricht der Aufruf mit
klarer Meldung ab; --kein-browser erzwingt den requests-Pfad. Fehlt
social_holen.py (Einzeldatei woandershin kopiert), bleibt alles beim Alten.

DIE BELEGPRUEFUNG IST DA. Frueher wurde nur der Titel gegen den Text geprueft,
das Datum nicht — und beim zweiten ernsthaften Fall meldete das Skript neun
Vernissagen im Wochenabstand, konstruiert aus 'Ausstellung 13.09. bis 08.11.,
geoeffnet sonntags'. Der Titel stimmte ja. Jetzt muss auch jedes Datum im Text
stehen; datumsfunde() erkennt die gaengigen Schreibweisen samt Jahresergaenzung
in rund dreissig Zeilen. Was --verbose daraus macht, ist der eigentliche Gewinn:
zu jedem Termin das Umfeld seines Datums. Steht dort 'bis', war es ein Zeitraum;
steht dort '11:30 Uhr', war es ein Termin.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:                                    # optional, nur fuer Social-Hosts (Instagram)
    import social_holen                 # Sibling in tools/ -- fehlt bei Einzeldatei-Kopie
except ImportError:
    social_holen = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ZEITLIMIT = 180        # Sekunden je claude-Aufruf
ABRUF_TIMEOUT = 20     # Sekunden je Seitenabruf
MAX_ZEICHEN = 30000    # Obergrenze, damit ein Ausreisser nicht 100.000 Token schickt
MAX_UNTERSEITEN = 4    # zusaetzlich zur Startseite, also hoechstens 5 Abrufe je Domain
MAX_BLAETTER = 5       # Folgeseiten einer geblaetterten Liste, je gelesener Seite
MINDESTPUNKTE = 3      # ein Stichwort im Linktext; ein Ordnername allein reicht nicht
KONTEXT_ZEICHEN = 55   # Umfeld je Belegstelle in der --verbose-Ausgabe
MAX_BELEGSTELLEN = 3   # mehr Fundstellen je Datum sagen nichts Neues
BESCHREIBUNG_MAX = 180 # Sicherheitsnetz: der Prompt bittet um 150, das ist die harte Grenze
BESCHREIBUNG_DECKUNG = 0.6  # so viel der Inhaltswoerter muss im Seitentext stehen (Erfindungs-Untergrenze)
SOCIAL_POSTS = 4       # Instagram: so viele der neuesten Beitraege lesen (social_holen)
BROWSER_PORT = 9222    # Chrome-Debug-Port fuer social_holen

# Haikus Ausgabegrenze, gemessen am 07.09.2026 (modelUsage.maxOutputTokens in der
# CLI-Antwort). Wird sie ueberschritten, liefert claude KEINE gekappte Antwort,
# sondern bricht ab: exit 1, is_error, und im result-Feld "Claude's response
# exceeded the ... output token maximum". Das faengt der returncode-Zweig in
# claude_fragen schon ab -- gefaehrlich ist nicht der Abbruch, sondern dass man
# ihn kommen sieht und nichts sagt. Der Vorderhaus-Lauf liegt bei rund 15.000
# Ausgabe-Token (130 Termine), also bei knapp der Haelfte.
AUSGABE_GRENZE = 32000
AUSGABE_WARNUNG = 0.75  # Anteil davon, ab dem eine Warnung auf stderr geht

# Woran eine Termin-Unterseite zu erkennen ist. Geprueft wird gegen Linktext UND
# URL-Pfad. Zwei Klassen, und der Unterschied traegt die ganze Auswahl:
#
# STARK   benennt eine Terminliste. Wer einen Link "Veranstaltungen" nennt,
#         meint eine Liste von Veranstaltungen. Reicht fuer sich allein.
# SCHWACH benennt ein Thema. "Ausstellungen" kann die Uebersicht sein oder eine
#         Zeile in "Biographische Daten, Ausstellungen" — bei der Stiftung fuer
#         Konkrete Kunst war genau das eine 3.771 Zeichen lange Lebenslaufseite
#         ohne einen einzigen kuenftigen Termin. Ein schwaches Wort braucht
#         deshalb Bestaetigung im Pfad.
#
# Bewusst nur deutsche und die gelaeufigen englischen Woerter — was hier fehlt,
# faellt durch, und das ist billiger als eine Liste, die halb Freiburg einsammelt.
#
# "tour" kam am 01.09.2026 dazu: murat-coskun.eu fuehrt auf der Startseite nur
# vier Termine, die vollstaendige Liste steht unter /on-tour — ohne Stichwort
# nie gelesen. Der vorhersehbare Fehltreffer (Tourist-Info, Tourismus) ist
# ueber NIE_TERMINE ausgeschlossen.
STARKE_STICHWORTE = ("veranstaltung", "termin", "konzert", "programm",
                     "kalender", "spielplan", "agenda", "spielzeit", "tour")
SCHWACHE_STICHWORTE = ("ausstellung", "aktuelles", "vorschau", "event",
                       "saison", "auffuehrung", "aufführung", "lesung",
                       "vernissage", "repertoire")
STICHWORTE = STARKE_STICHWORTE + SCHWACHE_STICHWORTE

# Endungen, hinter denen kein lesbarer Text steckt.
KEINE_SEITE = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip",
               ".doc", ".docx", ".xls", ".xlsx", ".mp3", ".mp4", ".ics")

# Woerter, die einen Link unabhaengig von allen Stichworten disqualifizieren.
# Der Vorderhaus verlinkt 'Newsletter abonnieren' mit einem Text, in dem
# 'Programm' und 'Konzerte' vorkommen — der Link schlug damit den echten
# Veranstaltungskalender. Eine Newsletter-Anmeldung ist nie eine Terminliste,
# egal wie sie beschriftet ist.
NIE_TERMINE = ("newsletter", "impressum", "datenschutz", "kontakt", "anfahrt",
               "agb", "spenden", "mitglied", "sponsor", "presse", "archiv",
               "rueckblick", "rückblick", "login", "warenkorb", "suche",
               "tourist", "tourismus")   # Gegengewicht zum Stichwort "tour"

# Jahreszahl in Pfad oder Linktext. Die Stiftung verlinkt eine Jahresnavigation
# von veranstaltungen_1999_2000.html bis veranstaltungen_2025.html — ohne diesen
# Filter kaemen zwanzig Archivseiten mit.
JAHR_IM_TEXT = re.compile(r"(19|20)\d{2}")

# Zerlegt einen URL-Pfad in Woerter. Ein Stichwort zaehlt nur, wenn es ein
# solches Wort ANFUEHRT -- '/events' und '/on-tour' ja, die Titel-Slugs
# '/event/ensemble-akademie-eroeffnungskonzert' nein. Ohne das gewinnt jede
# Einzelterminseite gegen ihre eigene Uebersicht: sie traegt das Stichwort im
# Linktext UND zweimal im Pfad. Bei ensemble-recherche.de frassen so zwei
# Seiten mit je einem Termin 10.476 Zeichen, waehrend /events abgeschnitten
# ankam und /Veranstaltungen ganz ausfiel.
PFAD_TRENNER = re.compile(r"[/\-_.]+")

# Ehrlicher Abrufkopf mit Kontaktadresse — dieselbe Haltung wie im uebrigen Projekt.
KOPFZEILEN = {"User-Agent": "kulturfein/1.0 (+mailto:info@exergia.de)"}

# Leerer Ordner ausserhalb des Projekts. Wird claude von hier aus gestartet,
# findet es keine CLAUDE.md.
ARBEITSORDNER = os.path.join(tempfile.gettempdir(), "kulturfein_claude_cwd")

# Siehe Kopf: ohne das denkt Haiku teuer und findet weniger.
OHNE_DENKEN = {"MAX_THINKING_TOKENS": "0"}

# Geschlossene Liste. Ohne Aufzaehlung erfindet das Modell Kategorien wie
# "Musiktheater" oder "Kulturveranstaltung", und die Auswertung zerfaellt.
# Umlaute sind umschrieben, weil der Auftrag als Kommandozeilenargument
# uebergeben wird und die Windows-Kommandozeile daran haengenbleiben kann.
_GENRES_STANDARD = ["Tanz", "Buehne", "Vortrag", "Spirituell", "Ausstellung",
                    "Konzert", "Lesung", "Workshop", "Sonstiges"]


def _lade_genres():
    """genres.md neben diesem Skript, sonst _GENRES_STANDARD.

    Haelt EIGENSTAENDIG (siehe Dateikopf) aufrecht: kopiert man nur diese eine
    Datei irgendwohin, laeuft sie trotzdem, mit demselben Standard, der vorher
    hart codiert war. Nur im Projekt selbst (genres.md danebenliegend) wird
    die Liste editierbar.
    """
    pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "genres.md")
    if not os.path.exists(pfad):
        return _GENRES_STANDARD
    with open(pfad, encoding="utf-8") as datei:
        werte = [w for zeile in datei if (w := zeile.split("#", 1)[0].strip())]
    return werte or _GENRES_STANDARD


GENRES = _lade_genres()


# ------------------------------------------------------------------ Region

# "Freiburg und Umgebung": nachpruefen() verwirft einen Termin, dessen `ort`
# keinen Namen aus eingaben/region.md nennt. FEHLT die Datei, bleibt der Filter
# AUS -- eine einzeln kopierte termine_aus_domain.py verhaelt sich dann wie
# zuvor (siehe "EIGENSTAENDIG" im Dateikopf). Nur im Projekt, wo die Liste
# liegt, greift die strenge Regionspruefung.
REGION_DATEI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "eingaben", "region.md")
# Termin ohne belegte Ortsangabe: behalten oder verwerfen? Das haengt vom
# DOMAIN-TYP ab, eine globale Antwort ist fuer beide Seiten falsch.
#
#   Spielstaette (rund 36 der 39 Domains) kuendigt ihr eigenes Programm an.
#   Der ort ist dort ein Raumname ("Kraeutergarten", "Haus St. Benedikt"), die
#   Geografie steckt in der Domain. Einen ort zu VERLANGEN kostete bei
#   kloster-st-lioba.de drei echte Klosterfuehrungen.
#
#   Tour-Domain (eingaben/tour-domains.md) spielt ueberall. Der ort TRAEGT die
#   geografische Information. Ihn nicht zu verlangen liess bei
#   ensemble-recherche.de Konzerte in Berlin und Wien in den Freiburger
#   Kalender rutschen.
#
# Deshalb kein globaler Schalter mehr, sondern der Parameter ort_pflicht an
# nachpruefen(); die Aufrufer leiten ihn ueber ist_tour() aus der Domain ab.
TOUR_DATEI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "eingaben", "tour-domains.md")


def _lade_region():
    """eingaben/region.md -> [ortsname, ...]; leere Liste, wenn die Datei fehlt.

    Ein Name je Zeile, '#' kommentiert, '##' gliedert -- dasselbe Format wie
    domains.md. Leere Liste heisst: kein Regionsfilter (siehe REGION_DATEI).
    """
    if not os.path.exists(REGION_DATEI):
        return []
    with open(REGION_DATEI, encoding="utf-8") as datei:
        return [n for zeile in datei if (n := zeile.split("#", 1)[0].strip())]


REGION = _lade_region()


def _lade_tour():
    """eingaben/tour-domains.md -> [domain, ...]; leer, wenn die Datei fehlt.

    Leere Liste heisst: jede Domain gilt als Spielstaette, ein fehlender ort
    verwirft nie. Das ist die vertraegliche Vorgabe fuer eine einzeln kopierte
    termine_aus_domain.py (siehe "EIGENSTAENDIG" im Dateikopf).
    """
    if not os.path.exists(TOUR_DATEI):
        return []
    with open(TOUR_DATEI, encoding="utf-8") as datei:
        return [d for zeile in datei if (d := zeile.split("#", 1)[0].strip())]


TOUR_DOMAINS = _lade_tour()


def ist_tour(ziel):
    """Domain ohne festes Haus? -> bool

    'ziel' darf die nackte Domain oder eine vollstaendige Adresse sein; geprueft
    wird als Teilstring auf der klein geschriebenen Form, damit
    'https://www.ensemble-recherche.de/events' genauso trifft wie
    'ensemble-recherche.de'.
    """
    z = (ziel or "").lower()
    return any(d.lower() in z for d in TOUR_DOMAINS)


def _in_region(ort):
    """Nennt `ort` einen Namen aus REGION? -> bool

    Teilstring auf der normalisierten Form (klein, Typografie geglaettet), damit
    'Kath. Pfarrkirche St. Peter' den Eintrag 'St. Peter' trifft und 'PILSEN
    (CZ)' keinen. Ohne REGION ist die Frage gegenstandslos -- nachpruefen()
    ruft dann gar nicht erst.
    """
    o = _normal(ort)
    return any(_normal(name) in o for name in REGION)


SYSTEMPROMPT = ("Du liest Text von Veranstalter-Websites und gibst Termine als "
                "JSON zurueck. Antworte ausschliesslich mit JSON, ohne Vorrede "
                "und ohne Code-Zaun.")

def _eintrag(anker):
    """Die Felder eines Eintrags. anker ist 'datum' oder 'rhythmus'.

    Einzelne und regelmaessige unterscheiden sich nur darin, woran sie
    haengen; alles
    andere ist gleich. Einmal beschrieben, damit die beiden Schemata nicht
    auseinanderlaufen koennen.
    """
    return {
        "type": "object",
        "properties": {
            anker: {"type": "string"},
            "uhrzeit": {"type": "string"},
            "titel": {"type": "string"},
            "kuenstler": {"type": "string"},
            "ort": {"type": "string"},
            "beschreibung": {"type": "string"},
            "genre": {"type": "string", "enum": GENRES},
            "fundstelle": {"type": "string"},
        },
        "required": [anker, "titel", "genre"],
    }


SCHEMA = json.dumps({
    "type": "object",
    "properties": {"termine": {"type": "array", "items": _eintrag("datum")}},
    "required": ["termine"],
}, ensure_ascii=False)

# Beide Listen sind Pflicht: ein leeres Array ist eine Aussage ("nichts
# gefunden"), ein fehlendes Feld nicht.
SCHEMA_TERMINE_REGELMAESSIG = json.dumps({
    "type": "object",
    "properties": {
        "termine": {"type": "array", "items": _eintrag("datum")},
        "termine_regelmaessig": {"type": "array", "items": _eintrag("rhythmus")},
    },
    "required": ["termine", "termine_regelmaessig"],
}, ensure_ascii=False)


def auftrag(heute):
    """Der Prompt. Was KEIN Termin ist, steht ausdruecklich drin — genau die
    Faelle, fuer die sonst Regexe entstehen.

    Der Absatz ueber Zeitraeume kam am 26.08.2026 dazu. Vorher stand da
    "Wiederholt sich eine Veranstaltung an mehreren Tagen, gib jeden Tag einzeln
    zurueck" — und aus "13.09.2026 bis 08.11.2026 ... Geoeffnet: Sonntags von
    11:30 bis 16:00 Uhr" baute das Modell prompt neun Vernissagen im
    Wochenabstand. Die Erlaubnis musste bleiben (das Klavierdepot spielt IMPERIA
    am 14. UND am 22. August), das Aufloesen eines Zeitraums musste weg.

    Der Absatz zum titel kam am 02.09.2026 dazu; vorher stand da nur "Titel
    wortgetreu aus dem Text". Das Modell schrieb den Titel trotzdem nicht ab,
    sondern BAUTE ihn aus mehreren Textstellen zusammen, und nachpruefen() warf
    ihn dann zu Recht als "steht nicht im Text" weg. Bei kreativpioniere zweimal
    beobachtet: den Rahmen 'Lesung zum Buch "..."' aus der Termin-Ueberschrift,
    den Buchtitel aber aus dem Fliesstext weiter unten (der ihn anders
    schreibt), dazu ein angehaengtes "von Katja Kosubek"; und
    'Joanne Calmel singt und spielt: Amour & Resistance. Chants du monde
    (Chanson / Weltmusik)' aus Kuenstlerin + Werktitel + Gattungsklammer. Jedes
    Fragment stand fuer sich im Text, die Kombination nirgends.

    Deshalb drei Verbote statt eines Gebots: nicht zusammensetzen, keinen Namen
    voranstellen, keine Gattung anhaengen. Ein Gebot ("wortgetreu") laesst dem
    Modell die Wahl, WAS es woertlich nimmt; die Verbote nehmen sie ihm.
    """
    return (
        f"Heute ist der {heute:%d.%m.%Y}. Lies den folgenden Text von einer "
        "Veranstalter-Website und gib alle ANGEKUENDIGTEN Veranstaltungen "
        "zurueck. Der Text kann mehrere Unterseiten enthalten, jeweils "
        "eingeleitet durch eine Zeile '--- <adresse> ---'.\n\n"
        "Datum als JJJJ-MM-TT, Uhrzeit als HH:MM (leer lassen, wenn keine "
        "angegeben ist).\n\n"
        + _FELDER +
        "Jedes zurueckgegebene Datum muss WORTWOERTLICH im Text stehen. Rechne "
        "nichts aus. Ein Zeitraum ('13.09.2026 bis 08.11.2026') ist EINE Angabe "
        "und keine Reihe von Einzelterminen — loese ihn nicht in Wochentage auf. "
        "Wiederkehrende Oeffnungszeiten ('Sonntags von 11:30 bis 16:00 Uhr') "
        "sind kein Termin. Sind fuer dieselbe Veranstaltung mehrere Daten "
        "einzeln genannt, gib jedes davon zurueck.\n\n"
        + _NICHTS_ERFINDEN
    )


# Die Feldbeschreibungen sind in beiden Auftragsfassungen wortgleich, und genau
# hier droht der Schaden der Doppelung: wer nur eine Kopie haertet, vergleicht
# spaeter zwei zufaellige Staende statt alt gegen neu. Deshalb stehen sie EINMAL
# da. Was die Fassungen wirklich unterscheidet -- Kopf, Zeitanker, Schluss --
# steht bei ihnen und ist damit auf einen Blick zu sehen.
_FELDER = (
        "titel ist EINE ZUSAMMENHAENGENDE Passage aus dem Text, Zeichen fuer "
        "Zeichen abgeschrieben — mit Anfuehrungszeichen, mit Tippfehlern, ohne "
        "Glaettung. Setze ihn NICHT aus mehreren Textstellen zusammen. Stelle "
        "keinen Namen voran (wer auftritt, gehoert in kuenstler) und haenge "
        "keine Gattungs- oder Spartenangabe an. Steht dieselbe Veranstaltung "
        "mehrfach im Text, nimm die kuerzeste Passage, die sie benennt.\n\n"
        "kuenstler ist, wer auftritt — Person oder Ensemble, wortgetreu aus "
        "dem Text ('Petra Gack', 'Ensemble-Akademie Freiburg'). Nicht der "
        "Veranstalter, nicht der Komponist. Leer lassen, wenn niemand genannt "
        "ist.\n\n"
        "ort ist der Veranstaltungsort, wortgetreu und zusammenhaengend aus "
        "dem Text. Nenne die Stadt oder den Ortsnamen MIT, wenn er im Text "
        "unmittelbar daneben steht ('Kraeutergarten Freiburg' statt nur "
        "'Kraeutergarten') — aber nur, wenn beides zusammenhaengend dasteht. "
        "Strasse und Hausnummer gehoeren NICHT hinein: 'Christuskirche "
        "Freiburg', nicht 'Christuskirche Freiburg Maienstrasse 2'. "
        "Leer lassen, wenn kein Ort angegeben ist.\n\n"
        "beschreibung fasst zusammen, WAS die Veranstaltung ist — Art, Thema, "
        "Anlass, Rahmen, Ort (hoechstens 150 Zeichen, ganze Saetze). Nenne "
        "darin KEINE Personennamen und KEINE Instrumente; wer auftritt, steht "
        "in kuenstler. So kann keine Besetzung verdreht werden. Keine "
        "Werbefloskeln, keine Ausrufezeichen. Leer lassen, wenn der Text "
        "nichts hergibt.\n\n"
        "genre ist genau einer dieser Werte:\n"
        + " | ".join(GENRES) + "\n\n"
        "fundstelle ist die Adresse aus der Zeile '--- <adresse> ---', die ueber "
        "dem Textabschnitt steht, in dem dieser Termin vorkommt. Kopiere sie "
        "wortgetreu. Steht der Termin in mehreren Abschnitten, nimm den mit den "
        "meisten Details. Nur eine der '--- <adresse> ---'-Zeilen, nichts "
        "anderes.\n\n"
)

_NICHTS_ERFINDEN = (
        "KEINE Veranstaltung sind: Nachrichten und Meldungen, Rueckblicke auf "
        "Vergangenes, Ausstellungsdauern, Oeffnungszeiten, Jahresarchive "
        "vergangener Spielzeiten, Pressemitteilungen, Anfahrtshinweise, "
        "Preisangaben.\n\n"
        "Erfinde nichts. Steht kein Termin im Text, gib eine leere Liste zurueck."
)


def auftrag_termine_regelmaessig(heute):
    """Dieselbe Aufgabe, aber mit zwei Listen: einzelne und regelmaessige Termine.

    BEFRISTET. Steht neben auftrag(), bis gemessen ist, ob die neue Fassung
    die bewaehrte Ausbeute haelt (siehe VARIANTEN). Dann wird sie die Vorgabe
    und die andere faellt weg.

    Der Grund fuer die zweite Liste: eine regelmaessige Veranstaltung ('jeden
    Dienstag 20 Uhr') hat kein Datum. Sie faellt heute doppelt durch -- der
    Prompt verbietet sie, und nachpruefen() koennte sie gar nicht belegen, weil
    es nichts zu belegen gibt. Damit fehlen Gottesdienste, Meditationskreise,
    offene Proben.

    Der Anker wechselt deshalb vom Datum auf die Regel: rhythmus traegt den
    Wiederholungstext woertlich aus der Seite und wird geprueft wie sonst der
    Titel. Das Faktenrueckgrat bleibt, nur sein Angelpunkt ist ein anderer.

    Die heikle Grenze ist die zur Oeffnungszeit. 'Sonntags von 11:30 bis 16:00
    Uhr' war der Ausloeser der neun Geistervernissagen (siehe auftrag) und darf
    auch als regelmaessiger Termin nicht durchkommen: eine Ausstellung, die
    sonntags geoeffnet hat, findet nicht sonntags statt. Deshalb steht der
    Satz ausdruecklich drin,
    und das Verbot, einen Zeitraum aufzuloesen, bleibt woertlich erhalten.
    """
    return (
        f"Heute ist der {heute:%d.%m.%Y}. Lies den folgenden Text von einer "
        "Veranstalter-Website und gib alle ANGEKUENDIGTEN Veranstaltungen "
        "zurueck. Der Text kann mehrere Unterseiten enthalten, jeweils "
        "eingeleitet durch eine Zeile '--- <adresse> ---'.\n\n"
        "Es gibt ZWEI Listen. In termine gehoert, was an einem ausgeschriebenen "
        "Datum stattfindet. In termine_regelmaessig gehoert, was sich nach einer im Text "
        "genannten Regel wiederholt, ohne dass Einzeldaten dastehen.\n\n"
        "Datum als JJJJ-MM-TT, Uhrzeit als HH:MM (leer lassen, wenn keine "
        "angegeben ist).\n\n"
        + _FELDER +
        "rhythmus ist EINE ZUSAMMENHAENGENDE Passage aus dem Text, Zeichen fuer "
        "Zeichen abgeschrieben, die sagt, WANN sich die Veranstaltung "
        "wiederholt ('jeden Dienstag', 'Sonntags 10 Uhr', 'jeden ersten Freitag "
        "im Monat'). Setze sie NICHT aus mehreren Textstellen zusammen und "
        "formuliere sie nicht um. Nur Eintraege in termine_regelmaessig haben einen "
        "rhythmus.\n\n"
        "Ein rhythmus muss eine WIEDERHOLUNG benennen. Kein rhythmus sind: ein "
        "Startzeitpunkt ('Ab September'), ein einzelnes Datum ('Naechster "
        "Termin am 08.09.26'), ein Zeitraum ('von Mai bis Juli'). Steht so "
        "etwas da, ist es entweder ein Termin fuer die andere Liste oder gar "
        "nichts — aber kein regelmaessiger Termin.\n\n"
        "Jedes zurueckgegebene Datum muss WORTWOERTLICH im Text stehen. Rechne "
        "nichts aus. Ein Zeitraum ('13.09.2026 bis 08.11.2026') ist EINE Angabe "
        "und keine Reihe von Einzelterminen — loese ihn nicht in Wochentage auf. "
        "Sind fuer dieselbe Veranstaltung mehrere Daten einzeln genannt, gib "
        "jedes davon zurueck.\n\n"
        "Stehen Einzeldaten ausgeschrieben da, gehoert jedes davon in termine — "
        "auch wenn es mehrere fuer dieselbe Veranstaltung sind. Nur wenn KEINE "
        "Einzeldaten dastehen, sondern eine Wiederholungsregel, gehoert der "
        "Eintrag in termine_regelmaessig.\n\n"
        "Oeffnungszeiten sind KEIN regelmaessiger Termin: eine Ausstellung, die sonntags "
        "geoeffnet hat ('Sonntags von 11:30 bis 16:00 Uhr'), findet nicht "
        "sonntags statt. Ein regelmaessiger Termin ist eine Veranstaltung, "
        "die zu einem festen "
        "Zeitpunkt beginnt.\n\n"
        + _NICHTS_ERFINDEN + " Dasselbe gilt fuer termine_regelmaessig."
    )


# Genau EINE Weiche, nicht vier. Auftrag, Schema und die zweite Pruefung gehoeren
# zusammen; verstreute if-Zweige waeren vier Stellen, an denen alter und neuer
# Weg unbemerkt auseinanderlaufen koennen.
#
# BEFRISTET: Zeigen zwei Vergleichslaeufe, dass die neue Fassung keine
# Einzeltermine in die zweite Liste abzieht und die Ausbeute haelt, wird
# "termine_regelmaessig" die Vorgabe und "bewaehrt" geloescht -- eine Zeile
# hier statt einer Suche durch die
# ganze Datei. Bleibt die zweite Liste dauerhaft leer, faellt umgekehrt die
# neue Fassung
# weg. Was nicht passieren darf, ist dass beide stehenbleiben.
VARIANTEN = {
    "bewaehrt": (auftrag,        SCHEMA,        False),
    "termine_regelmaessig": (auftrag_termine_regelmaessig,
                             SCHEMA_TERMINE_REGELMAESSIG, True),
}


# ------------------------------------------------------------------ Seiten holen

def _lies(antwort):
    """Antwort -> (text, suppe).

    bytes statt .text: so liest lxml das Encoding aus dem Meta-Tag und die
    Umlaute in den Titeln bleiben heil.
    """
    suppe = BeautifulSoup(antwort.content, "lxml")
    for weg in suppe(["script", "style", "noscript"]):
        weg.decompose()
    return suppe.get_text(" ", strip=True), suppe


def _hole_eine(adresse):
    """Eine Adresse -> (text, suppe, endadresse). Wirft bei Misserfolg."""
    antwort = requests.get(adresse, headers=KOPFZEILEN, timeout=ABRUF_TIMEOUT)
    antwort.raise_for_status()
    text, suppe = _lies(antwort)
    return text, suppe, antwort.url


def hole_startseite(ziel):
    """Domain oder Adresse -> (text, suppe, endadresse). Wirft bei Misserfolg.

    Manche Seiten laufen nur mit www., andere nur ohne — statt zu raten werden
    beide Schemata und beide Varianten probiert. Die Endadresse NACH
    Weiterleitungen kommt mit zurueck: klavierdepot-freiburg.de landet auf
    petra-gack.de/klavierdepot, und ohne diese Angabe waere kein Fund nachpruefbar.
    """
    if ziel.startswith("http"):
        kandidaten = [ziel]
    else:
        rumpf = ziel.rstrip("/")
        kandidaten = [f"https://{rumpf}", f"https://www.{rumpf}",
                      f"http://{rumpf}", f"http://www.{rumpf}"]

    letzter = None
    for kandidat in kandidaten:
        try:
            return _hole_eine(kandidat)
        except Exception as fehler:
            letzter = fehler
    raise letzter or RuntimeError("keine Adresse antwortete")


def waehle_unterseiten(suppe, startadresse, heute):
    """Links der Startseite -> ([(adresse, [stichworte])], [(adresse, grund)]).
    Kandidaten beste zuerst, dazu die am Jahresfilter gescheiterten.

    Rein heuristisch, ohne Modellaufruf. Zwei Regeln entscheiden fast alles:

    Stichworte in Linktext ODER Pfad — ein Link zaehlt so oft, wie er trifft.
    'Veranstaltungen, Konzerte' auf /veranstaltungen/veranstaltungen_2026.html
    trifft dreimal und landet vorn.

    Jahresfilter — der eigentlich wichtige Teil. Die Stiftung fuer Konkrete Kunst
    verlinkt eine Jahresnavigation von veranstaltungen_1999_2000.html bis
    veranstaltungen_2025.html. Jede dieser Seiten trifft das Stichwort; ohne den
    Filter kaemen zwanzig Archivseiten mit. Eine Jahreszahl kleiner als das
    laufende Jahr disqualifiziert den Link.

    Bei Punktgleichstand gewinnt der flachere Pfad: die Uebersicht steht ueber
    der Einzelseite, die von ihr verlinkt wird.

    Rueckgabe enthaelt die Stichworte und die Archiv-Ablehnungen, damit
    --verbose die Auswahl begruenden kann statt sie nur zu behaupten. Links ohne
    jedes Stichwort werden nicht einzeln gemeldet — das waeren bei jeder Seite
    zwei Dutzend Zeilen Impressum und Datenschutz.
    """
    heimat = _heimat(startadresse)
    bewertet, abgelehnt, gesehen = [], [], {_ohne_anker(startadresse)}

    for verweis in suppe.find_all("a", href=True):
        ziel = verweis["href"].strip()
        if not ziel or ziel.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        adresse = _ohne_anker(urljoin(startadresse, ziel))
        if adresse in gesehen:
            continue
        zerlegt = urlparse(adresse)
        if zerlegt.scheme not in ("http", "https") or _heimat(adresse) != heimat:
            continue
        if zerlegt.path.lower().endswith(KEINE_SEITE):
            continue

        beschriftung = verweis.get_text(" ", strip=True).lower()[:120]
        pfad = zerlegt.path.lower()
        if any(wort in beschriftung or wort in pfad for wort in NIE_TERMINE):
            continue
        punkte, treffer = _bewerte(beschriftung, pfad)
        if punkte < MINDESTPUNKTE:
            continue
        gesehen.add(adresse)
        archivjahr = _ist_archiv(pfad, beschriftung, heute)
        if archivjahr:
            abgelehnt.append((adresse, f"Archiv, Jahr {archivjahr} "
                                       f"< {heute.year}"))
            continue
        bewertet.append((adresse, punkte, treffer, len([teil for teil in pfad.split("/") if teil])))

    bewertet.sort(key=lambda eintrag: (eintrag[1], -eintrag[3]), reverse=True)
    return [(adresse, treffer) for adresse, _, treffer, _ in bewertet], abgelehnt


def _bewerte(beschriftung, pfad):
    """Linktext und Pfad -> (punkte, [stichworte])

    Der Linktext wiegt schwerer als der Pfad. Das ist der Unterschied zwischen
    einer Terminliste und einem Archiv: 'Geladene Kuenstler' auf
    /ausstellungen/kuenstler.html trifft nur ueber den Ordnernamen — und ist eine
    11.000 Zeichen lange Namensliste seit 1999, die beim ersten Versuch das halbe
    Zeichenbudget frass.

    Ein starkes Wort im Linktext genuegt (3 Punkte). Ein schwaches bringt 2 und
    braucht den Pfad dazu, um ueber MINDESTPUNKTE zu kommen — so kommt
    'Ausstellungen' auf /ausstellungen/ durch, 'Biographische Daten,
    Ausstellungen' auf /phleps/ dagegen nicht.

    Tiefe Pfade kosten Punkte. /ausstellungen/2026_weihs/weihs_wo_15_2016.html
    ist eine Bildseite, keine Uebersicht.

    Im Pfad zaehlt ein Stichwort nur am WORTANFANG (siehe PFAD_TRENNER), sonst
    schlaegt jede Einzelterminseite ihre eigene Uebersicht: /events bekam 4
    Punkte, /event/ensemble-akademie-eroeffnungskonzert 5 -- Stichwort im
    Linktext plus zweimal im Pfad, davon einmal mitten im Titel-Slug. Die
    Tiefenstrafe faengt das nicht, Detailseiten liegen bei Tiefe 2. Am
    03.09.2026 wurde stattdessen die Strafe ab Tiefe 1 probiert und wieder
    verworfen: sie warf bei stiftung-konkrete-kunst /ausstellungen/* und bei
    mehrklang /events/kategorie/* unter MINDESTPUNKTE.
    """
    woerter = PFAD_TRENNER.split(pfad)
    treffer = sorted({wort for wort in STICHWORTE
                      if wort in beschriftung
                      or any(teil.startswith(wort) for teil in woerter)})
    punkte = 0
    for wort in treffer:
        if wort in beschriftung:
            punkte += 3 if wort in STARKE_STICHWORTE else 2
        if any(teil.startswith(wort) for teil in woerter):
            punkte += 1
    tiefe = len([teil for teil in pfad.split("/") if teil])
    return punkte - max(0, tiefe - 2), treffer


def _heimat(adresse):
    """Adresse -> Host ohne fuehrendes 'www.'

    kloster-st-lioba.de liefert seine Startseite ohne www aus, verlinkt aber
    jede Unterseite mit. Verglich waehle_unterseiten die Hosts zeichengleich,
    galten alle 136 Links als fremde Domain: die Terminuebersicht mit den
    Uhrzeiten fiel heraus, und uebrig blieb die Startseite, auf der die
    Ankuendigungen ohne Uhrzeit stehen.

    Nur 'www.' faellt weg, keine anderen Subdomains -- shop.beispiel.de bleibt
    fremd, sonst laeuft der Scan in Ticketshops und Blogs.
    """
    host = urlparse(adresse).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _ohne_anker(adresse):
    """Adresse ohne #fragment — sonst gilt seite.html#oben als eigene Seite."""
    return adresse.split("#", 1)[0].rstrip("/") or adresse


def _ist_archiv(pfad, beschriftung, heute):
    """Traegt EIN Pfadsegment oder der Linktext nur Jahreszahlen, die AELTER
    als das laufende Jahr sind? -> das gefundene Jahr, sonst None

    Fruehere Fassung pruefte max(jahre) ueber den GANZEN Pfad und brach bei
    St. Peter: die Seite haengt Altjahre unter den laufenden Ordner
    (/orgelkonzerte-2026/orgelkonzerte-2019/...) — ueber den gesamten Pfad
    gerechnet gewinnt 2026, und eine 10.121 Zeichen lange Archivseite von
    2019 kam durch und verdraengte zwei echte 2026er-Kandidaten aus dem
    Zeichenbudget.

    Segmentweise erkennt das 2019er-Segment fuer sich, unabhaengig vom
    Elternordner. 'veranstaltungen_2020_2021.html' (ein Segment, zwei
    Jahre) ist Archiv. 'spielzeit-2025-2026' (ein Segment, gemischt) ist
    keins — das ist der Grund, nicht einfach min(jahre) zu nehmen. Ein
    Segment ohne Jahreszahl ist kein Archiv — im Zweifel wird gelesen, nicht
    verworfen.
    """
    for segment in pfad.split("/") + [beschriftung]:
        jahre = [int(m.group()) for m in JAHR_IM_TEXT.finditer(segment)]
        if jahre and max(jahre) < heute.year:
            return max(jahre)
    return None


def _blaetter_seiten(suppe, adresse, grenze):
    """Gelesene Seite -> Adressen ihrer Folgeseiten, Seitenzahl aufsteigend.

    Ein Blaetter-Link zeigt auf DIESELBE Seite -- gleicher Pfad, andere
    Abfrage -- und traegt als Beschriftung nur eine Ziffer.
    kloster-st-lioba.de zeigt 10 von 53 Terminen und haengt den Rest an
    '?pagerPage_f1092ea5=2' bis '=6'; ohne die endet der Scan Ende September,
    und die Klosterfuehrungen am 24.10. und 28.11. fehlen. Der Parametername
    ist seitenspezifisch, die Form nicht -- gesucht wird nur nach der Form.

    Seite 1 faellt weg, die steht schon da. Eine Folgeseite wird nicht
    ihrerseits weiterverfolgt: ihre Blaetterleiste zeigt dieselben Ziele,
    und der Texthash in sammle_seiten faengt nur gleiche, nicht kreisende
    Seiten ab.
    """
    hier = urlparse(adresse)
    gefunden = {}
    for verweis in suppe.find_all("a", href=True):
        beschriftung = verweis.get_text(" ", strip=True)
        if not beschriftung.isdigit() or int(beschriftung) < 2:
            continue
        ziel = _ohne_anker(urljoin(adresse, verweis["href"]))
        zerlegt = urlparse(ziel)
        if not zerlegt.query or _heimat(ziel) != _heimat(adresse):
            continue
        if zerlegt.path.rstrip("/") != hier.path.rstrip("/"):
            continue
        gefunden.setdefault(int(beschriftung), ziel)
    return [gefunden[nummer] for nummer in sorted(gefunden)[:grenze]]


def sammle_seiten(ziel, heute, protokoll=None, *, kein_browser=False,
                  browser_port=BROWSER_PORT):
    """Domain -> (gesamttext, startadresse, [(adresse, zeichen)]).

    Startseite, ihre Termin-Seiten und deren Folgeseiten, zu EINEM Text
    zusammengehaengt: bis zu MAX_UNTERSEITEN Kandidaten (siehe
    waehle_unterseiten) und je gelesener Seite bis zu MAX_BLAETTER Blaetter-
    Ziele (siehe _blaetter_seiten). Alles zusammen bleibt unter MAX_ZEICHEN;
    wer zuerst drankommt, bekommt den Platz.

    Und das alles in EINEM Modellaufruf, nicht einem je Seite: Auftrag und
    Systemprompt waeren sonst so oft zu bezahlen, wie Seiten gelesen wurden.

    Ein Textabschnitt beginnt mit '--- <adresse> ---'. Der Auftrag erklaert dem
    Modell diese Zeile; sie kostet ein Dutzend Token und macht im Zweifel
    nachvollziehbar, woher ein Fund stammt.

    Deduplizierung ueber einen Hash des Textes, nicht ueber die Adresse: bei der
    Stiftung liefern veranstaltungen/index.html und
    veranstaltungen/veranstaltungen_2026.html denselben Text, und der waere sonst
    zweimal bezahlt.

    SOCIAL-HOSTS gehen einen eigenen Weg (siehe Dateikopf): ist der Host bei
    social_holen bekannt und --kein-browser nicht gesetzt, liefert das Modul den
    Text aus einem ferngesteuerten Chrome, formgleich zurueck. social_holen fehlt
    (Einzeldatei-Kopie) oder --kein-browser -> normaler requests-Pfad.
    """
    def melde(zeile):
        if protokoll is not None:
            protokoll.append(zeile)

    if social_holen and not kein_browser and social_holen.ist_social(ziel):
        melde(f"  {ziel}  Social-Host, lese ueber Chrome auf :{browser_port}")
        return social_holen.hole(ziel, heute, MAX_ZEICHEN, browser_port,
                                 melde, SOCIAL_POSTS)

    text, suppe, startadresse = hole_startseite(ziel)
    melde(f"  {startadresse}  {len(text)} Z  (Startseite)")

    abschnitte = [f"--- {startadresse} ---\n{text}"]
    gelesen = [(startadresse, len(text))]
    bekannt = {hashlib.sha1(text.encode("utf-8")).hexdigest()}
    uebrig = MAX_ZEICHEN - len(abschnitte[0])

    kandidaten, abgelehnt = waehle_unterseiten(suppe, startadresse, heute)
    melde(f"  {len(suppe.find_all('a', href=True))} Links geprueft, "
          f"{len(kandidaten)} Kandidaten, {len(abgelehnt)} per Jahresfilter "
          f"verworfen, hoechstens {MAX_UNTERSEITEN} gelesen")
    for adresse, grund in abgelehnt:
        melde(f"  {adresse}  - {grund}")
    for adresse, treffer in kandidaten[MAX_UNTERSEITEN:]:
        melde(f"  {adresse}  - nachrangig ({', '.join(treffer)})")
    def nimm(adresse, notiz):
        """Eine Seite holen und an den Gesamttext haengen.

        Rueckgabe (suppe, endadresse) oder None, wenn nicht gelesen wurde --
        Budget erschoepft, nicht erreichbar, oder derselbe Text wie eine schon
        gelesene Seite. Steht als eigene Funktion da, weil Kandidaten und ihre
        Folgeseiten denselben Weg gehen; sie unterscheiden sich nur in der
        Herkunft, nicht in der Behandlung.
        """
        nonlocal uebrig
        if uebrig <= 0:
            melde(f"  {adresse}  uebersprungen (Zeichenbudget erschoepft)")
            return None
        try:
            seitentext, seitensuppe, endadresse = _hole_eine(adresse)
        except Exception as fehler:
            melde(f"  {adresse}  nicht erreichbar: {type(fehler).__name__}")
            return None

        fingerabdruck = hashlib.sha1(seitentext.encode("utf-8")).hexdigest()
        if fingerabdruck in bekannt:
            melde(f"  {adresse}  gleicher Text wie zuvor, uebersprungen")
            return None
        bekannt.add(fingerabdruck)

        kopf = f"--- {endadresse} ---\n"
        stueck = seitentext[:max(0, uebrig - len(kopf))]
        abschnitte.append(kopf + stueck)
        gelesen.append((endadresse, len(stueck)))
        uebrig -= len(kopf) + len(stueck)
        melde(f"  {endadresse}  {len(stueck)} Z  {notiz}")
        return seitensuppe, endadresse

    for adresse, treffer in kandidaten[:MAX_UNTERSEITEN]:
        gelesene_seite = nimm(adresse, f"+ {', '.join(treffer)}")
        if gelesene_seite is None:
            continue
        unterseite_suppe, endadresse = gelesene_seite
        for blatt in _blaetter_seiten(unterseite_suppe, endadresse, MAX_BLAETTER):
            nimm(blatt, "+ Folgeseite")

    # Zuletzt, nicht zuerst: die Blaetterleiste der Startseite fuehrt zu
    # aelteren Nachrichten, die Kandidatenseiten dagegen sind die vom
    # Punkteschema erkannten Terminlisten. Bei kloster-st-lioba.de nahm die
    # Startseiten-Folgeseite 3.564 Zeichen und kostete damit Seite 6 der
    # Terminliste -- 10 Termine gegen einen Nachrichtenauszug.
    for blatt in _blaetter_seiten(suppe, startadresse, MAX_BLAETTER):
        nimm(blatt, "+ Folgeseite der Startseite")

    return "\n\n".join(abschnitte), startadresse, gelesen


# -------------------------------------------------------------- claude rufen

def _json_herausschneiden(rohtext):
    """Das erste vollstaendige {...} aus einem Text. -> str oder ''

    Trotz --json-schema zaeunt das Modell die Antwort gern mit ```json ein. Statt
    darauf zu vertrauen, wird geschnitten.
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


def _fehlergrund(lauf):
    """Klartext-Ursache eines fehlgeschlagenen claude-Aufrufs. -> str

    Gemessen am 07.09.2026: bei ueberschrittener Ausgabegrenze endet die CLI mit
    exit 1, schreibt aber NICHTS auf stderr -- ihr JSON geht wie im Erfolgsfall
    nach stdout, mit "is_error": true und der Ursache im Feld 'result'. Deshalb
    erst dort nachsehen und stderr nur als Rueckfallebene nehmen.
    """
    try:
        antwort = json.loads(lauf.stdout or "")
        grund = str(antwort.get("result") or "").strip()
        if grund:
            return grund[:400]
    except (json.JSONDecodeError, AttributeError):
        pass
    return (lauf.stderr or lauf.stdout or "(keine Meldung)")[:400]


def claude_fragen(text, heute, modell="haiku", variante="bewaehrt"):
    """Der konfektionierte Aufruf. -> (inhalt, kennzahlen)

    Hier steckt der ganze Zweck des Skripts: Kontext, Modell, Bedingungen an Lauf
    und Ausgabe an einer Stelle, nachlesbar und aenderbar.

    inhalt ist das geparste Antwortobjekt: {"termine": [...]} und, bei der
    Variante "termine_regelmaessig", zusaetzlich die zweite Liste. None
    heisst Fehlschlag --
    kein Ergebnis, nicht ein leeres. Der Unterschied entscheidet, ob domain_lauf
    die Domain faellig laesst.
    """
    auftrag_bauen, schema, _ = VARIANTEN[variante]
    os.makedirs(ARBEITSORDNER, exist_ok=True)
    befehl = ["claude", "-p", auftrag_bauen(heute),
              "--system-prompt", SYSTEMPROMPT,   # ersetzt den Claude-Code-Prompt
              "--output-format", "json",
              "--json-schema", schema,           # erzwingt die Felder
              "--model", modell,
              "--tools", "",                     # keine Werkzeugbeschreibungen
              "--no-session-persistence"]
    try:
        lauf = subprocess.run(befehl, input=text, capture_output=True, text=True,
                              encoding="utf-8", timeout=ZEITLIMIT,
                              cwd=ARBEITSORDNER,          # weg vom Projektordner
                              env=dict(os.environ, **OHNE_DENKEN))
    except FileNotFoundError:
        print("FEHLER: 'claude' ist nicht im Pfad. Ohne Claude Code laeuft "
              "dieses Werkzeug nicht.", file=sys.stderr)
        return None, {}
    except subprocess.TimeoutExpired:
        print(f"FEHLER: keine Antwort binnen {ZEITLIMIT} s.", file=sys.stderr)
        return None, {}

    if lauf.returncode != 0:
        # Die Ursache steht in stdout, nicht in stderr: die CLI antwortet auch im
        # Fehlerfall mit ihrem JSON und legt den Klartext ins Feld 'result'
        # ("Claude's response exceeded the ... output token maximum"). Wer nur
        # stderr zeigt, sieht "endete mit 1" und weiss nichts.
        print(f"FEHLER: claude endete mit {lauf.returncode}\n"
              f"{_fehlergrund(lauf)}", file=sys.stderr)
        return None, {}

    try:
        antwort = json.loads(lauf.stdout)
    except json.JSONDecodeError:
        print(f"FEHLER: Antwort ist kein JSON:\n{lauf.stdout[:300]}", file=sys.stderr)
        return None, {}

    nutzung = antwort.get("usage", {})
    kennzahlen = {
        "kosten": round(antwort.get("total_cost_usd", 0.0), 6),
        "ein": nutzung.get("input_tokens", 0)
              + nutzung.get("cache_creation_input_tokens", 0)
              + nutzung.get("cache_read_input_tokens", 0),
        "aus": nutzung.get("output_tokens", 0),
    }
    if kennzahlen["aus"] > AUSGABE_GRENZE * AUSGABE_WARNUNG:
        print(f"WARNUNG: {kennzahlen['aus']} Ausgabe-Token, Grenze ist "
              f"{AUSGABE_GRENZE}. Diesmal gutgegangen; bei etwas mehr Terminen "
              f"bricht der Aufruf ab.", file=sys.stderr)

    inhalt = antwort.get("structured_output") or {}
    if not inhalt and antwort.get("result"):
        geschnitten = _json_herausschneiden(antwort["result"])
        try:
            inhalt = json.loads(geschnitten) if geschnitten else {}
        except json.JSONDecodeError:
            inhalt = {}
        # Kein verwertbares JSON, obwohl das Modell etwas gesagt hat: das ist ein
        # Fehlschlag und kein leeres Ergebnis. Der Unterschied entscheidet, ob
        # domain_lauf die Domain faellig laesst oder sie sieben Tage lang fuer
        # erfolgreich gescannt haelt (siehe dort ist_frisch). Der bekannte Weg
        # hierher -- eine zu lange Antwort -- endet schon oben mit exit 1; das
        # hier ist das Netz fuer die uebrigen.
        if not inhalt:
            print(f"FEHLER: Antwort enthaelt kein verwertbares JSON:\n"
                  f"{str(antwort['result'])[:300]}", file=sys.stderr)
            return None, kennzahlen
    return inhalt, kennzahlen


# --------------------------------------------------------------- Datumsbelege

# Drei Schreibweisen. Um jeden Trenner steht \s*, und das ist keine Kosmetik:
# das Klavierdepot schreibt "Freitag 14.August 2026 - 20h", OHNE Leerzeichen
# nach dem Punkt. Eine Suche nach fertigen Zeichenketten ("14. August 2026")
# haette dort alle vier echten Termine verworfen.
DATUM_NUMERISCH = re.compile(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4}|\d{2})?")
DATUM_MONATSNAME = re.compile(
    r"(\d{1,2})\s*\.?\s*"
    r"(jan|feb|mär|maer|mrz|apr|mai|jun|jul|aug|sep|okt|nov|dez)[a-zä]*\.?"
    r"\s*(\d{4})?", re.IGNORECASE)
DATUM_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

# Die vierte Form hat kein eigenes Datum, sondern eine Ueberschrift: Kalender
# schreiben "Oktober 27" und darunter nur noch die nackten Tage. Der Vorderhaus
# macht das, und ohne diese Regel hielt der Scanner alle 43 dort gemeldeten
# Termine fuer erfunden — das Modell hatte recht, die Pruefung war blind.
#
# Zwei Einschraenkungen, beide gemessen:
#
# Volle Wortgrenzen, sonst findet "mai" sein Monatsende in "Mainz".
#
# Kein Monatskopf, wenn eine Tageszahl davorsteht. "14.August 2026" beim
# Klavierdepot ist ein vollstaendiges Datum, keine Ueberschrift — als Kopf
# gelesen faerbte es den Rest der Seite ein und machte aus "- 20h" den 20.08.
MONATSKOPF = re.compile(
    r"(?<![\d.])\b(januar|februar|märz|maerz|april|mai|juni|juli|august|"
    r"september|oktober|november|dezember|jan|feb|mrz|apr|jun|jul|aug|sept|"
    r"sep|okt|nov|dez)\.?\s+((?:19|20)?\d{2})\b", re.IGNORECASE)

# Alleinstehend heisst: kein Zeichen eines groesseren Ausdrucks daneben. Ohne
# den Buchstabenausschluss wird die Uhrzeit "20h" zum zwanzigsten des Monats.
NACKTER_TAG = re.compile(r"(?<![\w.,:/-])(\d{1,2})(?![\w.,:/-])")

MONATSNUMMER = {"jan": 1, "feb": 2, "mär": 3, "maer": 3, "mrz": 3, "apr": 4,
                "mai": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10,
                "nov": 11, "dez": 12}


def _mit_jahr(tag, monat, jahr, heute):
    """Tag/Monat/Jahr -> [date, ...]. Ergaenzt ein fehlendes Jahr.

    Fruehere Fassung waehlte bei fehlendem Jahr EIN Jahr ('das naechste, in dem
    der Tag nicht vergangen ist') und warf den anderen Kandidaten weg. Das
    brach bei St. Peter: die Konzertreihe steht jahreslos ('23.08.', '30.08.'
    ...), und alles VOR dem Stichtag landete falsch im Folgejahr — am
    26.08.2026 galt '23.08.' als '2027-08-23' und damit als unbelegt, ein
    echter Termin fiel durch die Nachpruefung.

    datumsfunde() ist eine Existenzpruefung, keine Interpretation: sie muss
    nur wissen, ob IRGENDEIN Jahr zur Textstelle passt, nicht welches das
    Modell gemeint hat. Deshalb jetzt beide Kandidaten zurueckgeben, wenn kein
    Jahr im Text stand.
    """
    kandidaten = [jahr] if jahr else [heute.year, heute.year + 1]
    gefunden = []
    for versuch in kandidaten:
        try:
            gefunden.append(dt.date(versuch, monat, tag))
        except ValueError:
            pass
    return gefunden


def datumsfunde(text, heute):
    """Alle Datumsangaben des Textes -> {date: [(anfang, ende), ...]}

    ALLE Stellen je Datum, nicht nur die erste. Das ist keine Kleinigkeit: der
    08.11.2026 steht bei der Stiftung zweimal — auf der Startseite als Ende einer
    Ausstellungsdauer ('13.09.2026 bis 08.11.2026') und auf der
    Veranstaltungsseite als der Konzerttermin, um den es geht. Wer nur die erste
    Stelle zeigt, behauptet dem Leser gegenueber das Falsche.

    Die Positionen kommen mit, weil --verbose daraus das Umfeld schneidet. Genau
    dieses Umfeld ist die Diagnose: steht hinter dem Beleg ein 'bis', war es ein
    Zeitraum; steht dort '11:30 Uhr', war es ein Termin.
    """
    funde = {}

    def merke(daten, spanne):
        """daten: Liste moeglicher Kandidaten fuer dieselbe Textstelle (siehe
        _mit_jahr) — bei fehlendem Jahr mehr als einer, sonst genau einer."""
        for datum in daten:
            funde.setdefault(datum, []).append(spanne)

    for treffer in DATUM_NUMERISCH.finditer(text):
        tag, monat, jahr = int(treffer[1]), int(treffer[2]), treffer[3]
        if jahr:
            jahr = int(jahr) if len(jahr) == 4 else 2000 + int(jahr)
        merke(_mit_jahr(tag, monat, jahr, heute), treffer.span())

    for treffer in DATUM_MONATSNAME.finditer(text):
        monat = MONATSNUMMER.get(treffer[2].lower()[:4],
                                 MONATSNUMMER.get(treffer[2].lower()[:3]))
        if not monat:
            continue
        jahr = int(treffer[3]) if treffer[3] else None
        merke(_mit_jahr(int(treffer[1]), monat, jahr, heute), treffer.span())

    for treffer in DATUM_ISO.finditer(text):
        merke(_mit_jahr(int(treffer[3]), int(treffer[2]), int(treffer[1]), heute),
              treffer.span())

    for datum, spanne in _unter_monatskoepfen(text):
        merke([datum], spanne)

    for datum, spanne in _tage_vor_monat(text, heute):
        merke([datum], spanne)

    # Die Regexe laufen nacheinander, also nicht in Textreihenfolge, und
    # koennen dieselbe Stelle doppelt melden.
    return {datum: sorted(set(stellen)) for datum, stellen in funde.items()}


# "8., 9. und 10. Oktober": Tageszahlen VOR einem Monatsnamen, nur durch
# Aufzaehlungszeichen (',', '&', 'und', 'sowie') getrennt, gehoeren zu diesem
# Monat. Bewusst NICHT 'bis' oder '-': ein Zeitraum wird nicht in Einzeltage
# zerlegt (siehe Prompt), eine Aufzaehlung schon.
TAG_AUFZAEHLUNG = re.compile(
    r"(?:\d{1,2}\s*\.\s*(?:,|&|und|sowie|\s)*)+$", re.IGNORECASE)


def _tage_vor_monat(text, heute):
    """'8., 9. und 10. Oktober 2026' -> Belege fuer den 8. und 9.

    DATUM_MONATSNAME findet nur den letzten Tag ('10. Oktober'). Die Tageszahlen
    davor, nur durch ',', '&', 'und', 'sowie' getrennt, teilen sich Monat und
    Jahr des Ankers -- der Veranstalter schreibt die Reihe einmal aus. Bei
    betz.lucie stand 'am 8., 9. und 10. Oktober' im Text, das Modell gab alle
    drei zurueck, aber die Belegpruefung kannte nur den 10. und verwarf die
    anderen zwei zu Unrecht. 'bis'/'-' zaehlt NICHT als Trenner.
    """
    gefunden = []
    for anker in DATUM_MONATSNAME.finditer(text):
        monat = MONATSNUMMER.get(anker[2].lower()[:4],
                                 MONATSNUMMER.get(anker[2].lower()[:3]))
        if not monat:
            continue
        jahr = int(anker[3]) if anker[3] else None
        anfang = max(0, anker.start() - 60)
        kette = TAG_AUFZAEHLUNG.search(text[anfang:anker.start()])
        if not kette:
            continue
        basis = anfang + kette.start()
        for tag in re.finditer(r"(\d{1,2})\s*\.", kette.group()):
            spanne = (basis + tag.start(), basis + tag.end())
            for datum in _mit_jahr(int(tag[1]), monat, jahr, heute):
                gefunden.append((datum, spanne))
    return gefunden


def _unter_monatskoepfen(text):
    """Kalenderlisten der Form 'Oktober 27  3 Hinnerk Koehn  9 Yorick Thiede'
    -> [(date, spanne), ...]

    Ein Monatskopf faerbt den Text bis zum naechsten Monatskopf ein; jede
    alleinstehende Zahl 1..31 darin gilt als Tag dieses Monats. Das ist bewusst
    grosszuegig — es entstehen auch Belege aus Zahlen in Titeln ('25 JAHRE').

    Das ist die richtige Richtung fuer diesen Fehler: ein Beleg zu viel laesst
    einen erfundenen Termin durch, ein Beleg zu wenig wirft einen echten weg.
    Der Prompt haelt die erste Haelfte in Schach, sonst nichts die zweite.
    """
    koepfe = list(MONATSKOPF.finditer(text))
    gefunden = []
    for stelle, kopf in enumerate(koepfe):
        monat = MONATSNUMMER.get(kopf[1].lower()[:4],
                                 MONATSNUMMER.get(kopf[1].lower()[:3]))
        if not monat:
            continue
        jahr = int(kopf[2])
        jahr = jahr if jahr > 100 else 2000 + jahr
        bis = koepfe[stelle + 1].start() if stelle + 1 < len(koepfe) else len(text)
        for zahl in NACKTER_TAG.finditer(text, kopf.end(), bis):
            try:
                gefunden.append((dt.date(jahr, monat, int(zahl[1])), zahl.span()))
            except ValueError:
                pass
    return gefunden


def umfeld(text, spanne):
    """Text um eine Belegstelle, die Stelle in |Balken| -> str"""
    anfang, ende = spanne
    vorher = text[max(0, anfang - KONTEXT_ZEICHEN):anfang]
    nachher = text[ende:ende + KONTEXT_ZEICHEN]
    return f"...{vorher}|{text[anfang:ende]}|{nachher}..."


# ------------------------------------------------------------------- Nachpruefen

# St. Peter mischt vier Anfuehrungszeichen-Sorten ('Mit-Bach-durch-die-Regio'
# stand im Text mit "", im Modellfund mit "") plus Halbgeviertstriche. Das
# Modell normalisiert beim Zurueckgeben, der reine Kleinschreibungs-Vergleich
# schlug fehl und verwarf einen echten Titel. Auf Standardzeichen abbilden,
# bevor verglichen wird. None = loeschen: weiche Trennstriche und Nullbreiten-
# Zeichen stehen in manchem CMS-Text mitten im Wort und lassen sonst jeden
# Vergleich scheitern.
_TYPOGRAFIE = str.maketrans({
    "„": '"', "“": '"', "”": '"', "‚": "'", "’": "'",
    "«": '"', "»": '"', "–": "-", "—": "-", "‒": "-",
    "‑": "-",                       # geschuetzter Bindestrich
    "…": "...",
    "­": None, "​": None,      # weicher Trennstrich, Nullbreiten-Leerzeichen
    "‌": None, "‍": None,      # Nullbreiten-Nichtverbinder / -Verbinder
    "﻿": None,                      # BOM / Nullbreiten-No-Break
})


def _normal(s):
    return re.sub(r"\s+", " ", (s or "").translate(_TYPOGRAFIE).lower()).strip()


# Anfuehrungszeichen um einen Werktitel: die Seite setzt sie, das Modell laesst
# sie oft weg -- '"Brachland" - ein Oratorium' gegen 'Brachland - ein Oratorium'.
# _TYPOGRAFIE vereinheitlicht die Varianten nur (》 " « alle zu "), es ENTFERNT
# sie nicht; ein einziges fehlendes " liess den Teilstring-Test scheitern und
# warf einen echten Termin weg. Getilgt wird deshalb in der zweiten Stufe der
# Titelpruefung (siehe nachpruefen), die exakte erste Stufe bleibt unveraendert.
_QUOTES = re.compile(r"[\"'«»‘’‚“”„‹›]")


def _ohne_quotes(s):
    return _QUOTES.sub("", s)


def _kuerze(satz, grenze):
    """Auf <= grenze Zeichen, aber an einer Wortgrenze statt mitten im Wort.
    Wurde gekuerzt, endet der Rest auf '…' als Signal."""
    satz = (satz or "").strip()
    if len(satz) <= grenze:
        return satz
    return satz[:grenze].rsplit(" ", 1)[0].rstrip(" ,;:–-") + "…"


def _wortdeckung(satz, im_text):
    """Anteil der Inhaltswoerter (>= 4 Buchstaben) aus 'satz', die in 'im_text'
    vorkommen. -> 0.0..1.0; 1.0 wenn 'satz' keine Inhaltswoerter hat.

    Ersetzt fuer die beschreibung den exakten Substring-Test: das Modell
    formuliert die Beschreibung fast immer leicht um (Wortstellung, Grammatik),
    ein woertlicher Vergleich verwarf darum reihenweise brauchbare Saetze.
    Der Deckungsgrad faengt trotzdem eine frei erfundene Beschreibung ab.
    """
    woerter = re.findall(r"[^\W\d_]{4,}", _normal(satz))
    if not woerter:
        return 1.0
    return sum(1 for w in woerter if w in im_text) / len(woerter)


def _nebenfelder(fund, im_text, erlaubte_seiten, ort_pflicht, verbose):
    """Alles ausser titel und dem Zeitanker pruefen. -> (felder, grund)

    Bei Erfolg (dict, None), bei Regionsverstoss (None, grund) -- der ist der
    einzige Fehlschlag hier, der den ganzen Eintrag verwirft.

    Steht als eigene Funktion da, weil einzelne und regelmaessige Termine
    sich nur im Anker
    unterscheiden (Datum dort, Rhythmus hier) und in allem anderen nicht. Zwei
    Kopien dieser sechzig Zeilen wuerden auseinanderlaufen, sobald jemand nur
    eine haertet.

    kuenstler/ort/beschreibung werden gegen den Text geprueft, aber anders als
    beim Titel wirft ein Fehlschlag hier nicht den ganzen Eintrag weg — ein
    unbestaetigtes Nebenfeld macht einen bestaetigten Termin nicht ungueltig,
    genau wie ein unbekanntes Genre.

    kuenstler/ort sind kurze Eigennamen: woertlich pruefen, Faktenrueckgrat.
    beschreibung ist eine Zusammenfassung des Modells (WAS, nicht WER) — dort
    nur die Wortdeckung als Untergrenze gegen Erfundenes; Namen und Instrumente
    haelt der Prompt ganz raus, damit nichts verdreht wird.
    """
    genre = next((g for g in GENRES
                  if g.lower() == (fund.get("genre") or "").strip().lower()),
                 "Sonstiges")

    # kuenstler kann mehrere sein ('Lucie Betz, Miku Arizono'). Steht der
    # ganze String nicht so im Text, jeden Namen EINZELN pruefen und die
    # bestaetigten wieder zusammensetzen -- sonst faellt bei jeder
    # Doppelnennung das ganze Feld weg.
    kuenstler = (fund.get("kuenstler") or "").strip()
    if kuenstler and _normal(kuenstler) not in im_text:
        teile = re.split(r"\s*,\s*|\s+&\s+|\s+und\s+", kuenstler, flags=re.I)
        bestaetigt = [n.strip() for n in teile
                      if n.strip() and _normal(n) in im_text]
        kuenstler = ", ".join(dict.fromkeys(bestaetigt))
    # Haengt dem Modellwert ein Trenner an ('Murat Coskun, Beatriz Picas, '),
    # steht er oft trotzdem so im Text und der Zerleger oben greift nicht.
    kuenstler = re.sub(r"^[\s,;&]+|[\s,;&]+$", "", kuenstler)
    ort = fund.get("ort") or ""
    if ort and _normal(ort) not in im_text:
        ort = ""

    # Regionsfilter "Freiburg und Umgebung". Greift nur, wenn eingaben/
    # region.md vorliegt (sonst REGION == [], Block uebersprungen). Anders
    # als die Nebenfelder oben wirft ein Fehlschlag hier den GANZEN Eintrag
    # weg: ausserhalb der Region ist er kein Fund, sondern Rauschen.
    # `ort` ist an dieser Stelle bereits gegen den Seitentext belegt; ein
    # oben geleerter (unbelegter) `ort` zaehlt wie "keine Angabe".
    #
    # Ein FEHLENDER ort verwirft nur bei Tour-Domains (ort_pflicht). Dort
    # traegt der ort die Geografie, ohne ihn landen Berlin und Wien im
    # Freiburger Kalender. Bei Spielstaetten steckt die Geografie in der
    # Domain, dort waere Verwerfen der teurere Fehler (siehe TOUR_DATEI).
    if REGION:
        if ort and not _in_region(ort):
            return None, f"Ort ausserhalb der Region: {ort!r}"
        if not ort and ort_pflicht:
            return None, "ohne Ortsangabe, aber Tour-Domain"

    beschreibung = _kuerze(fund.get("beschreibung") or "", BESCHREIBUNG_MAX)
    if beschreibung:
        deckung = _wortdeckung(beschreibung, im_text)
        if deckung < BESCHREIBUNG_DECKUNG:
            if verbose:
                print(f"  beschreibung verworfen ({deckung:.0%}): "
                      f"{beschreibung!r}", file=sys.stderr)
            beschreibung = ""

    # fundstelle: die konkrete Seite, auf der der Eintrag steht. Muss eine der
    # gelesenen Adressen sein, sonst leer -- baue_webseite.py faellt dann auf
    # die Domain-Startseite zurueck (domain_log.json seiten[0]).
    fundstelle = (fund.get("fundstelle") or "").strip()
    if fundstelle and fundstelle.rstrip("/").lower() not in erlaubte_seiten:
        if verbose:
            print(f"  fundstelle verworfen (nicht gelesen): {fundstelle!r}",
                  file=sys.stderr)
        fundstelle = ""

    # Reihenfolge wie bisher: sie bestimmt, wie termine.json aussieht, und ein
    # umsortiertes Feld waere ein Diff ohne Inhalt.
    return {"kuenstler": kuenstler, "ort": ort, "beschreibung": beschreibung,
            "genre": genre, "fundstelle": fundstelle}, None


def nachpruefen(funde, text, heute, verbose=False, seiten=None, ort_pflicht=False):
    """Titel UND Datum muessen im Text stehen, Genre aus der Liste.
    -> (gute, verworfene, belege)

    seiten: die tatsaechlich gelesenen Adressen (fuer die fundstelle-Pruefung).
    Eine fundstelle, die nicht darunter ist, wird verworfen -> leer.

    Bis zum 26.08.2026 wurde nur der Titel geprueft. Das reichte, solange nichts
    schieflief, und versagte beim ersten Ernstfall: die Stiftung fuer Konkrete
    Kunst meldete neun Vernissagen im Wochenabstand, alle mit demselben echten
    Titel, sieben davon mit einem Datum, das nirgends auf der Seite steht.

    Ein unbekanntes Genre wird weiterhin auf 'Sonstiges' gesetzt statt
    verworfen — ein falsches Etikett macht einen echten Termin nicht ungueltig.
    Ein erfundenes Datum schon.

    Der TITEL wird zweistufig geprueft: erst woertlich, dann ohne
    Anfuehrungszeichen auf beiden Seiten (_ohne_quotes). Die Seite schreibt
    '"Brachland" - ein Oratorium', das Modell liefert mal mit, mal ohne die
    Zeichen — am 02.09. lieferte derselbe Text deswegen mal 8, mal 5
    uebernommene Termine. Die zweite Stufe weicht nichts auf: die Wortfolge
    muss weiterhin exakt im Text stehen. Das DATUM bleibt einstufig und hart;
    es ist der eigentliche Halluzinations-Anker.

    Liegt eingaben/region.md vor, faellt zusaetzlich alles raus, dessen `ort`
    keinen Ort/keine Spielstaette der Liste nennt ("Freiburg und Umgebung");
    ohne die Datei bleibt dieser Schritt aus. Siehe _in_region / REGION.

    ort_pflicht: bei Tour-Domains (eingaben/tour-domains.md) verwirft auch ein
    FEHLENDER ort, denn dort traegt er die Geografie. Bei Spielstaetten nicht --
    siehe TOUR_DATEI fuer die Begruendung beider Richtungen.

    titel/datum/kuenstler/ort werden woertlich gegen den Text gehalten — sie
    sind das Faktenrueckgrat, da darf nichts kippen. beschreibung ist eine vom
    Modell formulierte Zusammenfassung; woertlich pruefen geht da nicht. Gegen
    frei Erfundenes greift die Wortdeckung (siehe _wortdeckung, Schwelle
    BESCHREIBUNG_DECKUNG), darunter wird das Feld geleert (mit verbose=True auf
    stderr vermerkt), der Termin bleibt.

    Eine Wortdeckung sieht KEINE Rollenverdrehung ('Butoh-Taenzerin am E-Piano').
    Dagegen haelt der Prompt Namen und Instrumente ganz aus der beschreibung
    heraus (die stehen in kuenstler) -- ohne Instrumenten-Slot laesst sich auch
    keine Besetzung falsch zuordnen.

    belege bildet Datum -> alle Belegstellen ab, fuer --verbose.
    """
    im_text = _normal(text)
    # Einmal vorab, nicht je Fund: im_text ist bis zu MAX_ZEICHEN lang.
    im_text_blank = _ohne_quotes(im_text)
    vorhanden = datumsfunde(text, heute)
    # Fundstelle darf nur eine der tatsaechlich gelesenen Seiten sein. Vergleich
    # ohne Schrägstrich am Ende und ohne Gross-/Kleinschreibung, sonst nichts.
    erlaubte_seiten = {a.rstrip("/").lower() for a in (seiten or [])}
    gut, verworfen, belege = [], [], {}
    for fund in funde:
        titel = fund.get("titel") or ""
        try:
            datum = dt.date.fromisoformat(fund.get("datum", ""))
        except (ValueError, TypeError):
            verworfen.append((fund, "Datum unlesbar"))
            continue
        if not titel:
            verworfen.append((fund, "kein Titel"))
            continue
        # Zwei Stufen: erst woertlich, dann ohne Anfuehrungszeichen auf BEIDEN
        # Seiten. Die zweite ist keine Aufweichung -- '"Brachland"' und
        # 'Brachland' sind derselbe Titel, die Wortfolge muss weiterhin exakt
        # stimmen, ein erfundener Titel wird so nicht gefunden. Sie nimmt
        # ausserdem die groesste Quelle der Lauf-zu-Lauf-Schwankung raus: ob das
        # Modell die Anfuehrungszeichen mitschreibt, ist Zufall (derselbe Text
        # lieferte am 02.09. mal 8, mal 5 uebernommene Termine, nur deswegen).
        if (_normal(titel) not in im_text
                and _ohne_quotes(_normal(titel)) not in im_text_blank):
            verworfen.append((fund, "Titel steht nicht im Text"))
            continue
        if datum not in vorhanden:
            verworfen.append((fund, "Datum steht nicht im Text"))
            continue

        felder, grund = _nebenfelder(fund, im_text, erlaubte_seiten,
                                     ort_pflicht, verbose)
        if felder is None:
            verworfen.append((fund, grund))
            continue

        belege[fund["datum"]] = vorhanden[datum]
        gut.append({"datum": fund["datum"], "uhrzeit": fund.get("uhrzeit") or "",
                    "titel": titel, **felder})
    return sorted(gut, key=lambda t: (t["datum"], t["uhrzeit"])), verworfen, belege


# Was einen Rhythmus ausmacht. Ein blosser Wochentag reicht ("Dienstag, 20:00 -
# 22:00 Uhr" steht so im Programm des Tibet-Kailash-Hauses und meint jeden
# Dienstag); ein Wiederholungswort reicht auch allein ("14-taegig").
_WIEDERHOLUNG = re.compile(
    r"(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag"
    r"|jede[nrs]?\b|alle\s+\d|woechentlich|wöchentlich|monatlich|jaehrlich"
    r"|jährlich|taeglich|täglich|14-?taegig|14-?tägig|regelmaessig|regelmäßig"
    r"|immer\b|stets\b|wochentags|werktags)", re.I)

# Ein konkretes Datum ist das Gegenteil einer Wiederholung. Bewusst enger als
# datumsfunde(): hier genuegt die Form, es geht nicht um Belegbarkeit.
_KONKRETES_DATUM = re.compile(
    r"\d{1,2}\s*\.\s*\d{1,2}\s*\.|\d{1,2}\.\s*(?:Januar|Februar|Maerz|März|April"
    r"|Mai|Juni|Juli|August|September|Oktober|November|Dezember)|\d{4}-\d{2}-\d{2}",
    re.I)


def _ist_rhythmus(rhythmus):
    """Nennt diese Passage eine Wiederholung? -> (bool, grund)

    Die Belegpruefung sagt nur, dass der Text auf der Seite steht. Ob er eine
    WIEDERHOLUNG benennt, ist eine andere Frage, und beide Fehlfunde des ersten
    Laufs scheiterten genau daran: 'Ab September' und 'Naechste Termin am
    08.09.26' standen wortgetreu da und waren trotzdem keine Rhythmen.
    """
    if _KONKRETES_DATUM.search(rhythmus):
        return False, f"Rhythmus nennt ein konkretes Datum: {rhythmus!r}"
    if not _WIEDERHOLUNG.search(rhythmus):
        return False, f"Rhythmus nennt keine Wiederholung: {rhythmus!r}"
    return True, ""


def pruefe_termine_regelmaessig(regelmaessige, text, verbose=False,
                                seiten=None, ort_pflicht=False):
    """Titel UND Rhythmus muessen im Text stehen. -> (gute, verworfene)

    Dieselbe Haerte wie nachpruefen(), nur mit einem anderen Anker. Ein Termin
    haengt an einem Datum, das im Text belegbar ist; ein regelmaessiger hat
    keins. Ohne
    Ersatz waere sie unbelegbar, und unbelegte Eintraege sind genau das, wogegen
    dieses Werkzeug gebaut ist (siehe nachpruefen: neun Vernissagen).

    Der Ersatz ist rhythmus: die Passage, die die Wiederholung benennt, woertlich
    aus der Seite. Sie wird zweistufig geprueft wie der Titel -- erst genau, dann
    ohne Anfuehrungszeichen. Steht sie nicht da, hat das Modell die Regel
    formuliert statt abgeschrieben, und der Eintrag faellt.

    Woertlich abgeschrieben heisst aber noch nicht "eine Wiederholung". Der
    erste Lauf ueber die Testflaeche am 07.09.2026 lieferte zwei solche
    Eintraege, und
    beide waren falsch, obwohl beide Passagen so auf der Seite standen:
    'Ab September' (ein Startzeitpunkt) und 'Naechste Termin am 08.09.26' (ein
    Einzeldatum, das als Termin gehoert haette). Die Belegpruefung kann das
    nicht sehen -- sie prueft Existenz, nicht Bedeutung.

    Deshalb zusaetzlich _ist_rhythmus(): ein Wochentag oder ein Wiederholungswort
    muss vorkommen, ein konkretes Datum nicht. Das ist dieselbe Bauart wie der
    Rest des Werkzeugs -- eine lokale Regel gegen das, was das Modell
    plausibel, aber falsch liefert.

    Kein Datumsbeleg, keine belege-Rueckgabe: es gibt nichts zu belegen und
    nichts, dessen Umfeld man zeigen koennte.
    """
    im_text = _normal(text)
    im_text_blank = _ohne_quotes(im_text)
    erlaubte_seiten = {a.rstrip("/").lower() for a in (seiten or [])}
    gut, verworfen = [], []
    for fund in regelmaessige or []:
        titel = fund.get("titel") or ""
        rhythmus = (fund.get("rhythmus") or "").strip()
        if not titel:
            verworfen.append((fund, "kein Titel"))
            continue
        if not rhythmus:
            verworfen.append((fund, "kein Rhythmus"))
            continue
        if (_normal(titel) not in im_text
                and _ohne_quotes(_normal(titel)) not in im_text_blank):
            verworfen.append((fund, "Titel steht nicht im Text"))
            continue
        if (_normal(rhythmus) not in im_text
                and _ohne_quotes(_normal(rhythmus)) not in im_text_blank):
            verworfen.append((fund, "Rhythmus steht nicht im Text"))
            continue
        taugt, warum = _ist_rhythmus(rhythmus)
        if not taugt:
            verworfen.append((fund, warum))
            continue

        felder, grund = _nebenfelder(fund, im_text, erlaubte_seiten,
                                     ort_pflicht, verbose)
        if felder is None:
            verworfen.append((fund, grund))
            continue

        gut.append({"rhythmus": rhythmus, "uhrzeit": fund.get("uhrzeit") or "",
                    "titel": titel, **felder})
    return sorted(gut, key=lambda r: (r["rhythmus"], r["uhrzeit"])), verworfen


# ------------------------------------------------------------------- Darstellen

def als_text(ergebnis, heute):
    """Lesbare Fassung eines Ergebnisses. -> str

    Gibt einen String zurueck statt zu drucken, damit dieselbe Fassung wahlweise
    auf stdout oder in eine Datei gehen kann. Das ist der ganze Trick hinter der
    Trennung von --json (wie) und --out (wohin).
    """
    zeilen = [f"# {ergebnis['ziel']}"]
    quelle = ergebnis.get("quelle", "")
    if quelle and quelle.rstrip("/") not in (
            f"https://{ergebnis['ziel']}".rstrip("/"), ergebnis["ziel"].rstrip("/")):
        zeilen.append(f"  gelesen: {quelle}")
    if "fehler" in ergebnis:
        zeilen.append(f"  {ergebnis['fehler']}")
        return "\n".join(zeilen)

    seiten = ergebnis.get("seiten", [])
    if len(seiten) > 1:
        zeilen.append(f"  {len(seiten)} Seiten, {ergebnis['zeichen']} Zeichen")
        for seite in seiten[1:]:
            zeilen.append(f"    + {seite['adresse']}")
    else:
        zeilen.append(f"  Text {ergebnis['zeichen']} Zeichen")
    zeilen.append("")
    zeilen.append(f"  {ergebnis['gemeldet']} gemeldet, "
                  f"{len(ergebnis['termine'])} uebernommen, "
                  f"{ergebnis['verworfen']} verworfen")
    zeilen.append("")
    for t in ergebnis["termine"]:
        kuenftig = "  " if dt.date.fromisoformat(t["datum"]) >= heute else " (vorbei)"
        zeile = (f"  {t['datum']}  {t['uhrzeit'] or '  :  '}  "
                 f"{t['genre']:<24}  {t['titel'][:44]}{kuenftig}")
        if t.get("kuenstler"):
            zeile += f"  ~ {t['kuenstler'][:28]}"
        if t.get("ort"):
            zeile += f"  @ {t['ort'][:30]}"
        zeilen.append(zeile)
        if t.get("beschreibung"):
            zeilen.append(f"      {t['beschreibung']}")
        if t.get("fundstelle"):
            zeilen.append(f"      -> {t['fundstelle']}")
    # Regelmaessige stehen unter den Terminen, nicht dazwischen: sie haben
    # kein Datum,
    # nach dem sie sich einsortieren liessen, und ihre Zahl ist klein.
    if ergebnis.get("termine_regelmaessig"):
        zeilen.append("")
        zeilen.append(f"  REGELMAESSIG ({len(ergebnis['termine_regelmaessig'])})")
        for r in ergebnis["termine_regelmaessig"]:
            zeile = (f"  {r['rhythmus'][:24]:<24}  {r['uhrzeit'] or '  :  '}  "
                     f"{r['genre']:<12}  {r['titel'][:44]}")
            if r.get("kuenstler"):
                zeile += f"  ~ {r['kuenstler'][:28]}"
            if r.get("ort"):
                zeile += f"  @ {r['ort'][:30]}"
            zeilen.append(zeile)
            if r.get("beschreibung"):
                zeilen.append(f"      {r['beschreibung']}")
            if r.get("fundstelle"):
                zeilen.append(f"      -> {r['fundstelle']}")
    # Titel NICHT kuerzen: die Verwerfungszeile ist eine Diagnosezeile. Genau der
    # abgeschnittene Teil war zuletzt der, den man zum Vergleich mit dem
    # Seitentext gebraucht haette.
    for fund, grund in ergebnis.get("_verworfen", []):
        zeilen.append(f"  VERWORFEN  {fund.get('datum') or fund.get('rhythmus') or '?'}  "
                      f"{fund.get('titel')!r}  — {grund}")
    k = ergebnis["tokens"]
    zeilen.append("")
    zeilen.append(f"  Tokens: {k['ein']} ein / {k['aus']} aus · "
                  f"Kosten: {ergebnis['kosten_usd']:.4f} USD")
    return "\n".join(zeilen)


def belege_zeigen(gut, verworfen, belege, text):
    """Der zweite --verbose-Block: wo im Text steht das gemeldete Datum?

    Geht auf stderr wie der Abrufblock. Die Zeile mit dem Umfeld ist der
    eigentliche Zweck des ganzen Schalters — an ihr sieht man, ob ein Datum
    einen Termin bezeichnet oder das Ende einer Ausstellungsdauer:

        <<13.09.2026>>  ...Wiegandt |13.09.2026| bis 08.11.2026 Helga Weihs...

    Das 'bis' hinter dem Balken beantwortet die Frage, ohne die Seite zu oeffnen.
    """
    print("BELEGE", file=sys.stderr)
    for termin in gut:
        # Startseite und Unterseite tragen oft denselben Satz. Zwei Stellen mit
        # gleichem Wortlaut sind zwei Fundorte, aber nur eine Auskunft.
        gezeigt = []
        for spanne in belege.get(termin["datum"], []):
            zeile = umfeld(text, spanne)
            if zeile not in gezeigt:
                gezeigt.append(zeile)
            if len(gezeigt) >= MAX_BELEGSTELLEN:
                break
        mehrfach = f"   ({len(gezeigt)} Fundstellen)" if len(gezeigt) > 1 else ""
        print(f"  {termin['datum']}  {termin['genre']:<12}  "
              f"{termin['titel'][:48]}{mehrfach}", file=sys.stderr)
        for zeile in gezeigt:
            print(f"     {zeile}", file=sys.stderr)
    for fund, grund in verworfen:
        print(f"  {fund.get('datum', '?')}  VERWORFEN     "
              f"{fund.get('titel')!r}", file=sys.stderr)
        print(f"     {grund}", file=sys.stderr)
    if not gut and not verworfen:
        print("  (nichts gemeldet)", file=sys.stderr)


def ausgeben(ergebnis, heute, als_json, ziel_datei):
    """Format waehlen, Ziel waehlen, ausgeben.

    Die beiden Entscheidungen sind unabhaengig — vier Faelle aus zwei Schaltern:

                       stdout                 Datei
        lesbar         (nichts)               --out x.txt
        JSON           --json                 --json --out x.json

    Der Hinweis auf die geschriebene Datei geht auf stderr, damit
    'termine_aus_domain foo.de --json --out x.json' und eine Pipe sich nicht ins Gehege
    kommen.
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


def vergleich_zeigen(text, heute, modell, seiten, ort_pflicht):
    """Beide Auftragsfassungen auf DENSELBEN Text, Ergebnisse nebeneinander.

    Der Grund, warum die Weiche im Code sitzt und nicht in zwei Git-Staenden:
    nur so sehen beide Prompts denselben Seitenstand. Sonst enthielte jede
    Differenz auch die Aenderungen der Website zwischen zwei Laeufen.

    Was ueberdauert: die Schwankung des Modells selbst. Derselbe Text lieferte
    am 02.09. mal 8, mal 5 uebernommene Termine (siehe nachpruefen). Ein
    einzelner Durchgang beweist deshalb nichts -- entscheidend ist die Zeile
    "nur einzeln": Titel, die die neue Fassung als Termin verloren hat. Steht
    einer davon drueben unter REGELMAESSIG, ist genau die Verschiebung
    passiert, gegen
    die dieser Vergleich gebaut ist.
    """
    ergebnisse = {}
    for name in VARIANTEN:
        inhalt, k = claude_fragen(text, heute, modell, name)
        if inhalt is None:
            print(f"  {name}: keine Antwort", file=sys.stderr)
            return
        gut, verworfen, _ = nachpruefen(inhalt.get("termine", []), text, heute,
                                        False, seiten, ort_pflicht)
        regelmaessige, regelmaessig_verworfen = pruefe_termine_regelmaessig(
            inhalt.get("termine_regelmaessig"), text,
                                                 False, seiten, ort_pflicht)
        ergebnisse[name] = (gut, verworfen, regelmaessige, regelmaessig_verworfen, k)
        print(f"  {name:<8} {len(gut)} Termine, {len(regelmaessige)} regelmaessig, "
              f"{len(verworfen) + len(regelmaessig_verworfen)} verworfen, "
              f"{k.get('kosten', 0.0):.4f} USD", file=sys.stderr)

    a_gut, _, _, _, _ = ergebnisse["bewaehrt"]
    n_gut, _, n_regelmaessig, _, _ = ergebnisse["termine_regelmaessig"]
    # Schluessel ist (datum, titel), nicht der Titel allein: die Sternensee-Band
    # spielt ihr "Dreisam-Bruecken-Konzert" fuenfmal an fuenf Daten. Als
    # Titelmenge waere das EIN Eintrag, und der Vergleich meldete Gleichstand,
    # waehrend vier Termine fehlen.
    a_schluessel = {(t["datum"], t["titel"]) for t in a_gut}
    n_schluessel = {(t["datum"], t["titel"]) for t in n_gut}
    regelmaessig_titel = {r["titel"] for r in n_regelmaessig}

    print("", file=sys.stderr)
    nur_alt = sorted(a_schluessel - n_schluessel)
    if nur_alt:
        print(f"  nur einzeln ({len(nur_alt)}) — als Termin verloren:",
              file=sys.stderr)
        for datum, titel in nur_alt:
            wohin = ("  >>> steht drueben unter REGELMAESSIG"
                     if titel in regelmaessig_titel else "")
            print(f"    {datum}  {titel[:58]}{wohin}", file=sys.stderr)
    else:
        print("  nur einzeln: keine — kein Termin ist verlorengegangen",
              file=sys.stderr)

    nur_neu = sorted(n_schluessel - a_schluessel)
    if nur_neu:
        print(f"  nur neue Fassung ({len(nur_neu)}) — zusaetzlich als Termin:",
              file=sys.stderr)
        for datum, titel in nur_neu:
            print(f"    {datum}  {titel[:58]}", file=sys.stderr)

    if n_regelmaessig:
        print(f"\n  REGELMAESSIG ({len(n_regelmaessig)}):", file=sys.stderr)
        for r in n_regelmaessig:
            print(f"    {r['rhythmus'][:30]:<30} {r['uhrzeit'] or '  :  '}  "
                  f"{r['titel'][:44]}", file=sys.stderr)
    else:
        print("\n  REGELMAESSIG: keine", file=sys.stderr)


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
                          help="Modell fuer claude -p (Vorgabe: haiku)")
    zerleger.add_argument("--show-prompt", action="store_true", dest="show_prompt",
                          help="Dialog mit claude auf stderr zeigen: HINWEG "
                               "(system-prompt, auftrag, json-schema, Seitentext) "
                               "und RUECKWEG (rohe Modellantwort vor nachpruefen)")
    zerleger.add_argument("--verbose", action="store_true",
                          help="auf stderr zeigen, welche Unterseiten gelesen "
                               "wurden und in welchem Umfeld jedes Datum steht")
    zerleger.add_argument("--kein-browser", action="store_true", dest="kein_browser",
                          help="Social-Hosts (Instagram) nicht ueber den Chrome "
                               "lesen, sondern wie jede andere Seite ueber requests "
                               "(bekommt dort nur die Bio)")
    zerleger.add_argument("--browser-port", type=int, default=BROWSER_PORT,
                          dest="browser_port",
                          help=f"Chrome-Debug-Port fuer Social-Hosts "
                               f"(Vorgabe: {BROWSER_PORT})")
    zerleger.add_argument("--termine-regelmaessig", action="store_true",
                          help="regelmaessige Termine ('jeden Dienstag') als "
                               "zweite Liste mitnehmen. BEFRISTET, siehe "
                               "VARIANTEN")
    zerleger.add_argument("--vergleich", action="store_true",
                          dest="vergleich",
                          help="beide Auftragsfassungen auf DENSELBEN "
                               "Seitentext ansetzen und die Ergebnisse "
                               "gegenueberstellen (zwei Modellaufrufe)")
    argumente = zerleger.parse_args()

    heute = dt.date.today()
    variante = ("termine_regelmaessig"
                if (argumente.termine_regelmaessig or argumente.vergleich)
                else "bewaehrt")
    auftrag_bauen, schema, _ = VARIANTEN[variante]
    ergebnis = {"ziel": argumente.ziel, "quelle": "",
                "abgerufen": f"{heute:%Y-%m-%d}", "termine": []}

    def abbrechen(meldung):
        """Fehlerfall: geht denselben Weg wie ein Erfolg, damit --out und --json
        auch dann greifen."""
        ergebnis["fehler"] = meldung
        ausgeben(ergebnis, heute, argumente.als_json, argumente.out)
        return 1

    # Das Protokoll faellt beim Abruf an, also bevor feststeht, ob er gelingt.
    # Es wird auch im Fehlerfall gezeigt — gerade dann ist es das Interessante.
    protokoll = [] if argumente.verbose else None
    try:
        text, quelle, gelesen = sammle_seiten(
            argumente.ziel, heute, protokoll,
            kein_browser=argumente.kein_browser,
            browser_port=argumente.browser_port)
    except Exception as fehler:
        if protokoll:
            print("ABRUF\n" + "\n".join(protokoll), file=sys.stderr)
        hinweis = str(fehler) if fehler.args else type(fehler).__name__
        return abbrechen(f"nicht erreichbar: {hinweis}")

    if argumente.verbose:
        print("ABRUF", file=sys.stderr)
        print("\n".join(protokoll), file=sys.stderr)
        print(f"  -> {len(gelesen)} Seiten, {len(text)} Zeichen an das Modell\n",
              file=sys.stderr)

    ergebnis["quelle"] = quelle
    gekappt = text[:MAX_ZEICHEN]
    if argumente.show_prompt:
        # Alles, was an claude geht -- die Anweisung UND der Text. Vorher zeigte
        # dieser Schalter nur den Seitentext; genau die Anweisung, um die es beim
        # Debuggen der Wortlaut-Treue geht, blieb unsichtbar.
        print("=== HINWEG 1/4: system-prompt ===", file=sys.stderr)
        print(SYSTEMPROMPT, file=sys.stderr)
        print(f"\n=== HINWEG 2/4: auftrag ({variante}) ===", file=sys.stderr)
        print(auftrag_bauen(heute), file=sys.stderr)
        print("\n=== HINWEG 3/4: json-schema ===", file=sys.stderr)
        print(json.dumps(json.loads(schema), ensure_ascii=False, indent=2),
              file=sys.stderr)
        print(f"\n=== HINWEG 4/4: seitentext ueber stdin ({len(gekappt)} Zeichen) ===",
              file=sys.stderr)
        print(gekappt, file=sys.stderr)
        print("=== Ende HINWEG ===\n", file=sys.stderr)

    if argumente.vergleich:
        vergleich_zeigen(gekappt, heute, argumente.modell,
                         [a for a, _ in gelesen], ist_tour(argumente.ziel))
        return 0

    inhalt, k = claude_fragen(gekappt, heute, argumente.modell, variante)
    if inhalt is None:
        return abbrechen("claude lieferte keine Antwort")
    funde = inhalt.get("termine", [])

    if argumente.show_prompt:
        # Die ROHE Modellantwort, vor nachpruefen und ungekuerzt. Nur hier sieht
        # man, was das Modell woertlich als titel/ort/datum geliefert hat -- die
        # Voraussetzung, um Prompt-Fehler von Pruef-Fehlern zu unterscheiden.
        # BEIDE Listen, sonst bliebe unklar, ob das Modell nichts lieferte oder
        # die Pruefung zuschlug.
        print(f"=== RUECKWEG: rohe Modellantwort ({len(funde)} Termine, "
              f"{len(inhalt.get('termine_regelmaessig') or [])} regelmaessige, "
              f"vor nachpruefen) ===",
              file=sys.stderr)
        print(json.dumps(inhalt, ensure_ascii=False, indent=2), file=sys.stderr)
        print("=== Ende RUECKWEG ===\n", file=sys.stderr)

    seiten = [a for a, _ in gelesen]
    ort_pflicht = ist_tour(argumente.ziel)
    gut, verworfen, belege = nachpruefen(funde, gekappt, heute, argumente.verbose,
                                         seiten=seiten, ort_pflicht=ort_pflicht)
    if argumente.verbose:
        belege_zeigen(gut, verworfen, belege, gekappt)
        print("", file=sys.stderr)

    gute_regelmaessige, verworfene_regelmaessige = pruefe_termine_regelmaessig(
        inhalt.get("termine_regelmaessig"), gekappt, argumente.verbose,
        seiten=seiten, ort_pflicht=ort_pflicht)

    ergebnis["termine"] = gut
    if argumente.termine_regelmaessig:
        ergebnis["termine_regelmaessig"] = gute_regelmaessige
    ergebnis["gemeldet"] = len(funde) + len(inhalt.get("termine_regelmaessig") or [])
    ergebnis["verworfen"] = len(verworfen) + len(verworfene_regelmaessige)
    ergebnis["_verworfen"] = verworfen + verworfene_regelmaessige
    ergebnis["seiten"] = [{"adresse": a, "zeichen": z} for a, z in gelesen]
    ergebnis["zeichen"] = len(gekappt)
    ergebnis["kosten_usd"] = k.get("kosten", 0.0)
    ergebnis["tokens"] = {"ein": k.get("ein", 0), "aus": k.get("aus", 0)}

    ausgeben(ergebnis, heute, argumente.als_json, argumente.out)
    return 0 if (gut or gute_regelmaessige) else 1


if __name__ == "__main__":
    sys.exit(main())
