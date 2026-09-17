#!/usr/bin/env python3
"""termine.json -> index.html. Reines Rendern, kein Modellaufruf, keine Kosten.

Eigener Befehl, kein Schalter an domain_lauf.py — dieselbe Trennung, die
schon zwischen termine_aus_domain.py (ein Aufruf) und domain_lauf.py
(Buchhaltung ueber viele Laeufe) gilt. Wer nur die Seite neu bauen will, ohne
neu zu scannen, ruft einfach dieses Skript.

Template kopiert und angepasst aus dem Nachbarprojekt
schwarzes_brett_webseite_test/tools/templates/index.html.j2 (Zeitungs-/
Amtsblatt-Stil, kein JavaScript, vollstaendig serverseitig gerendert) --
bewusst KOPIERT statt referenziert, damit kulturfein nicht von einem
Pfad in einem fremden Projektordner abhaengt. Angepasst: deren Schema
(place/title/description, zweistufig tag+topic) passt nicht auf unseres
(ort/titel/beschreibung/kuenstler, einstufig genre) -- siehe README.

KEIN FENSTER NOETIG, aber EINE GRUPPIERUNG. Die alte Vorlage filterte ein
rollierendes Zeitfenster und deduplizierte per Hash-ID, weil ihre
events.json auch Vergangenes und Dubletten enthalten konnte. Vergangenes ist
in termine.json schon keins mehr (domain_lauf.py raeumt es bei jedem Lauf).
Dubletten aber gibt es in zwei Sorten, und domain_lauf faengt nur die eine:
Rescan-Dubletten JE DOMAIN (verschmelze() trennt fremd/eigen, gleicher_termin()
verlangt gleiche domain). Quellen-Dubletten UEBER DOMAINS -- dasselbe Konzert
auf drei Veranstalter-Seiten -- bleiben stehen. Die sammelt _gruppiere() hier
beim Rendern ein: reine Darstellungsfrage, termine.json bleibt der ehrliche
Fund-je-Domain-Bestand. Je Cluster wird nur der vollstaendigste Datensatz
gezeigt, die uebrigen entfallen fuer den Bau.

DER LINK JE TERMIN kommt nicht aus termine.json (das traegt nur die nackte
Domain, keine URL) -- er wird aus domain_log.json nachgeschlagen:
seiten[0] ist die Startadresse dieser Domain nach Weiterleitung.

    python tools/baue_webseite.py              # index.html im Projekt-Root schreiben
    python tools/baue_webseite.py --spur test  # test-termine.json -> test-index.html
"""
import argparse
import datetime as dt
import difflib
import json
import os
import re
import sys
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader

from termine_aus_domain import GENRES, _normal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HIER = os.path.dirname(os.path.abspath(__file__))
PROJEKT = os.path.dirname(HIER)

TEMPLATE_ORDNER = os.path.join(HIER, "templates")


def _pfade(spur=""):
    """Namenspraefix -> (termine, domain_log, domains, ausgabe, regelmaessig).
    Leer = Produktion.

    Gegenstueck zu _pfade() in domain_lauf.py: '--spur test' rendert
    ausgaben/test-termine.json nach test-index.html, ohne index.html anzufassen.
    Bewusst dupliziert statt geteilt -- der gemeinsame Import waere
    termine_aus_domain.py, und das soll laut Dateikopf EIGENSTAENDIG bleiben und
    kennt weder termine.json noch index.html. regelmaessig folgt demselben
    Namensmuster wie in domain_lauf.py._pfade().
    """
    p = f"{spur}-" if spur else ""
    return (os.path.join(PROJEKT, "ausgaben", f"{p}termine.json"),
            os.path.join(PROJEKT, "ausgaben", f"{p}domain_log.json"),
            os.path.join(PROJEKT, "eingaben", f"{p}domains.md"),
            os.path.join(PROJEKT, f"{p}index.html"),
            os.path.join(PROJEKT, "ausgaben", f"{p}termine_regelmaessig.json"))


TERMINE, DOMAIN_LOG, DOMAINS, AUSGABE, TERMINE_REGELMAESSIG = _pfade()

WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]   # date.weekday(): 0=Montag
                                                          # fest verdrahtet statt
                                                          # strftime('%a') -- das
                                                          # haengt vom Locale der
                                                          # Maschine ab, hier nicht.

# Farbe + CSS-taugliches Kuerzel je Genre. Genres mit Leerzeichen waeren als
# CSS-Variablenname unbrauchbar, deshalb ein eigenes Kuerzel statt den Namen
# direkt zu verwenden.
GENRE_FARBEN = {
    "Tanz": ("tanz", "--genre-tanz"),
    "Buehne": ("buehne", "--genre-buehne"),
    "Vortrag": ("vortrag", "--genre-vortrag"),
    "Spirituell": ("spirituell", "--genre-spirituell"),
    "Ausstellung": ("ausstellung", "--genre-ausstellung"),
    "Konzert": ("konzert", "--genre-konzert"),
    "Lesung": ("lesung", "--genre-lesung"),
    "Workshop": ("workshop", "--genre-workshop"),
    "Sonstiges": ("sonstiges", "--genre-sonstiges"),
}

# Genre-Werte sind ASCII (siehe genres.md: gehen als --json-schema an claude).
# Wo der Anzeige-Name davon abweicht, hier eintragen -- Slug und CSS-Variable
# bleiben trotzdem am rohen Wert haengen.
ANZEIGE_NAME = {"Buehne": "Bühne"}

# Weiche Warnung statt hartem Assert: seit GENRES aus genres.md geladen wird
# (siehe termine_aus_domain.py), kann dort ein Genre auftauchen, fuer das
# hier noch keine Farbe eingetragen ist -- das soll die Seite nicht zum
# Abbruch bringen, nur sichtbar machen. Fallback auf die Sonstiges-Farbe
# passiert ohnehin schon ueber GENRE_FARBEN.get(..., GENRE_FARBEN["Sonstiges"])
# weiter unten in baue_tage().
_fehlende_farben = set(GENRES) - set(GENRE_FARBEN)
if _fehlende_farben:
    print(f"WARNUNG: keine Farbe fuer Genre(s) {sorted(_fehlende_farben)} -- "
          f"faellt auf Sonstiges-Farbe zurueck. GENRE_FARBEN in baue_webseite.py "
          f"ergaenzen, um eine eigene Farbe zu vergeben.", file=sys.stderr)


def _lade_json(pfad, vorgabe):
    if not os.path.exists(pfad):
        return vorgabe
    with open(pfad, encoding="utf-8") as datei:
        return json.load(datei)


# Pflichtfelder laut Schema in termine_aus_domain.py: datum, titel, genre.
# Die Pipeline haelt das ein; kommt trotzdem ein Datensatz ohne eins davon an
# (von Hand editiert, Altbestand), soll er die ganze Seite nicht zum Absturz
# bringen -- dieselbe weiche Haltung wie bei den fehlenden Genre-Farben oben.
_PFLICHT = ("datum", "titel", "genre")

# Regelmaessige Termine haben kein datum, dafuer einen rhythmus (siehe
# termine_aus_domain.py: pruefe_termine_regelmaessig).
_PFLICHT_REGELMAESSIG = ("rhythmus", "titel", "genre")


def _nur_gueltige(termine, pflicht=_PFLICHT):
    gueltig = []
    for t in termine:
        fehlt = [f for f in pflicht if not t.get(f)]
        if fehlt:
            kennung = t.get("titel") or t.get("datum") or t.get("domain") or "?"
            print(f"WARNUNG: Termin ohne {', '.join(fehlt)} uebersprungen "
                  f"({kennung}).", file=sys.stderr)
        else:
            gueltig.append(t)
    return gueltig


def _lade_domains(pfad):
    """Wie lade_domains() in domain_lauf.py -- Split auf das erste '#' statt
    startswith(), damit 'foo.de  # Name, Charakter' beim Aktivieren
    funktioniert statt als ein Domainstring samt Kommentar gelesen zu werden.
    """
    if not os.path.exists(pfad):
        return []
    with open(pfad, encoding="utf-8") as datei:
        return [k for z in datei if (k := z.split("#", 1)[0].strip())]


# Domains, die einer einzelnen Person gehoeren (eigener Instagram-Account,
# eigene Webseite), nicht spur-abhaengig -- eine strukturelle Zuordnung wie
# region.md/tour-domains.md in termine_aus_domain.py, kein Testdatum.
PERSONEN_DATEI = os.path.join(PROJEKT, "eingaben", "personen-domains.md")


def _lade_personen(pfad):
    """eingaben/personen-domains.md -> {domain (klein): Name}; leer, wenn die
    Datei fehlt. Format 'domain = Name', '#' kommentiert.
    """
    if not os.path.exists(pfad):
        return {}
    personen = {}
    with open(pfad, encoding="utf-8") as datei:
        for zeile in datei:
            zeile = zeile.split("#", 1)[0].strip()
            if not zeile or "=" not in zeile:
                continue
            domain, name = zeile.split("=", 1)
            personen[domain.strip().lower()] = name.strip()
    return personen


def _mit_person(kuenstler, domain, personen):
    """kuenstler-String, ergaenzt um die Person aus personen-domains.md,
    falls die Domain ihr gehoert und ihr Name noch nicht drin steht.

    Reine Darstellungsanreicherung wie _gruppiere() -- termine.json bleibt
    unveraendert. Anlass: das Modell nennt eine Person, die einen Post nur
    einmal als Bio/Signatur unterschreibt (statt im Termin-Absatz selbst),
    nicht zuverlaessig -- das ist aber keine Interpretationsfrage, sondern
    eine feste Tatsache der Domain, die nicht neu erraten werden muss.
    """
    name = personen.get((domain or "").lower())
    if not name or (kuenstler and _normal(name) in _normal(kuenstler)):
        return kuenstler
    return f"{kuenstler}, {name}" if kuenstler else name


def _link(termin, log):
    """Termin -> Adresse zum Anklicken.

    Bevorzugt die 'fundstelle' des Termins (die konkrete Unterseite, auf der er
    steht). Fehlt sie, faellt es auf die Domain-Startseite nach Weiterleitung
    zurueck: domain_log.json, seiten[0] (erstes Element ist per Konstruktion
    immer die Startadresse nach Weiterleitung).
    """
    if termin.get("fundstelle"):
        return termin["fundstelle"]
    seiten = log.get(termin.get("domain", ""), {}).get("seiten") or []
    return seiten[0] if seiten else ""


def _host(url):
    """URL -> 'mehrklang-freiburg.de' (ohne Schema, ohne www., ohne Pfad).
    Dient als sichtbare Beschriftung des Termin-Links."""
    if not url:
        return ""
    netz = urlparse(url).netloc.lower()
    return netz[4:] if netz.startswith("www.") else netz


# ---------------------------------------------- Quellen-Dubletten (ueber Domains)

AEHNLICH_SCHWELLE = 0.6    # SequenceMatcher-Ratio, s. _aehnlich
_WORT = re.compile(r"[^\W\d_]{4,}")   # Kernwort: Buchstaben, >= 4, keine Ziffern


def _aehnlich(a, b):
    """Zwei Zeichenketten -> bool. Teilstring, dann SequenceMatcher-Ratio.

    Wie domain_lauf._aehnlich, aber bewusst KOPIERT statt importiert: dort geht
    es um Rescan-Dubletten JE DOMAIN, hier um Quellen-Abgleich UEBER Domains --
    die Schwellen duerfen sich fachlich getrennt bewegen. Order-sensitiv, taugt
    fuer Orte und als Rueckfall bei titel-losen Eintraegen; fuer Titel siehe
    _titel_passt (dieselbe Veranstaltung heisst je Veranstalter anders herum).
    """
    na, nb = _normal(a), _normal(b)
    if not na or not nb:
        return na == nb
    if na in nb or nb in na:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= AEHNLICH_SCHWELLE


def _titel_passt(a, b):
    """Zwei Titel -> bool, ueber die MENGE der Kernworte statt ihrer Reihenfolge.

    'Ensemble-Akademie Eroeffnungskonzert' und 'Eroeffnungskonzert der Ensemble-
    Akademie Freiburg' meinen dasselbe, SequenceMatcher sieht das wegen der
    Wortstellung nicht. Gezaehlt werden geteilte Kernworte (>= 4 Buchstaben,
    ohne Zahlen wie '2026'): mindestens zwei (oder alle des kuerzeren, wenn der
    nur eins hat) und Ueberdeckung des kuerzeren >= 0.7.
    """
    wa, wb = set(_WORT.findall(_normal(a))), set(_WORT.findall(_normal(b)))
    if not wa or not wb:
        return _aehnlich(a, b)
    gemeinsam = wa & wb
    klein = min(len(wa), len(wb))
    return len(gemeinsam) >= min(2, klein) and len(gemeinsam) / klein >= 0.7


def _ort_passt(a, b):
    """Zwei ort-Strings -> bool. Leer auf einer Seite zaehlt als Treffer (datum
    + uhrzeit + Titel tragen dann schon). Sonst: _aehnlich ODER ein gemeinsames
    Wort ab 5 Buchstaben ('christuskirche' in 'Christuskirche Freiburg' und
    'Christuskirche Maienstrasse, Freiburg i.Br.')."""
    na, nb = _normal(a), _normal(b)
    if not na or not nb:
        return True
    if _aehnlich(na, nb):
        return True
    lang = set(re.findall(r"[^\W\d_]{5,}", na))
    return any(w in lang for w in re.findall(r"[^\W\d_]{5,}", nb))


def _selbes_event(a, b):
    """Bezeichnen zwei Eintraege VERSCHIEDENER Domains dieselbe Veranstaltung?

    datum und uhrzeit exakt (leer == leer, wie gleicher_termin in domain_lauf),
    Titel UND Ort muessen zusammenpassen. Beides, nicht nur eins: am 2026-09-24
    20:00 stehen 'Troja: Reich. Sexy. Unbesiegbar.' (Schopf2) und 'ZUR NACHT im
    Freiburger Muenster' -- gleiches datum+uhrzeit, aber weder Titel noch Ort
    aehnlich, also kein Cluster.
    """
    return (a.get("datum") == b.get("datum")
            and (a.get("uhrzeit") or "") == (b.get("uhrzeit") or "")
            and _titel_passt(a.get("titel"), b.get("titel"))
            and _ort_passt(a.get("ort"), b.get("ort")))


def _vollstaendigkeit(t):
    """Sortierschluessel: welcher Datensatz eines Clusters wird gezeigt?
    Mehr belegte Felder gewinnen, dann laengere beschreibung, dann laengerer
    Titel, dann domain alphabetisch -- Letzteres nur, damit die Wahl von Lauf
    zu Lauf stabil bleibt."""
    belegt = sum(1 for f in ("titel", "kuenstler", "ort", "beschreibung") if t.get(f))
    return (belegt, len(t.get("beschreibung") or ""), len(t.get("titel") or ""),
            t.get("domain") or "")


def _gruppiere(termine):
    """Flache Terminliste -> Liste ohne Quellen-Dubletten.

    Jeder Termin kommt in den ersten Cluster, dessen Kopf _selbes_event trifft,
    sonst eroeffnet er einen neuen. Je Cluster bleibt nur der vollstaendigste
    Datensatz uebrig (max nach _vollstaendigkeit); die uebrigen Meldungen
    derselben Veranstaltung entfallen fuer den Bau. termine.json bleibt
    unangetastet -- das hier ist reine Darstellung.
    """
    cluster = []
    for t in termine:
        for gruppe in cluster:
            if _selbes_event(gruppe[0], t):
                gruppe.append(t)
                break
        else:
            cluster.append([t])
    return [max(gruppe, key=_vollstaendigkeit) for gruppe in cluster]


def baue_tage(termine, log, heute, personen):
    """Flache Terminliste -> [{weekday, date, is_today, entries: [...]}, ...]

    Gruppiert nach datum, absteigend... nein, aufsteigend nach Datum, und
    innerhalb eines Tages nach Uhrzeit (fehlende Uhrzeit ans Ende). 'Heute'
    bleibt als Abschnitt sichtbar, auch ohne Eintraege -- Orientierungspunkt,
    genau wie im Vorbild.
    """
    nach_tag = {}
    for t in termine:
        nach_tag.setdefault(t["datum"], []).append(t)

    tage_daten = sorted(set(nach_tag) | {heute.isoformat()})

    tage = []
    for datum_iso in tage_daten:
        datum = dt.date.fromisoformat(datum_iso)
        eintraege = sorted(nach_tag.get(datum_iso, []),
                           key=lambda t: t.get("uhrzeit") or "99:99")
        gerendert = []
        for t in eintraege:
            slug, var = GENRE_FARBEN.get(t["genre"], GENRE_FARBEN["Sonstiges"])
            gerendert.append({
                "titel": t["titel"], "uhrzeit": t.get("uhrzeit") or "",
                "kuenstler": _mit_person(t.get("kuenstler") or "", t.get("domain"), personen),
                "ort": t.get("ort") or "",
                "beschreibung": t.get("beschreibung") or "",
                "genre": ANZEIGE_NAME.get(t["genre"], t["genre"]),
                "genre_slug": slug, "genre_farbe": var,
                "link": (link := _link(t, log)), "link_label": _host(link),
            })
        tage.append({"weekday": WOCHENTAGE[datum.weekday()], "date": datum_iso,
                     # date bleibt ISO -- das braucht data-date fuer den
                     # String-Vergleich im JS (heuteIso()). date_anzeige ist
                     # nur fuer den sichtbaren Text.
                     "date_anzeige": datum.strftime("%d.%m.%Y"),
                     "is_today": datum_iso == heute.isoformat(), "entries": gerendert})
    return tage


# Reihenfolge Mo..So; 'sonnabend' als Synonym auf denselben Index wie 'samstag'.
_WOCHENTAG_STAEMME = [("montag", 0), ("dienstag", 1), ("mittwoch", 2),
                      ("donnerstag", 3), ("freitag", 4), ("samstag", 5),
                      ("sonnabend", 5), ("sonntag", 6)]


def _wochentag_index(rhythmus):
    """rhythmus-Text -> Index Mo=0..So=6, oder 7 als Fallback (kein Wochentag
    erkannt). Bei mehreren genannten Wochentagen ('dienstags und donnerstags')
    gewinnt der zuerst im Text genannte, nicht der alphabetisch erste Stamm --
    das ist die Reihenfolge, die die Seite selbst nennt."""
    text = _normal(rhythmus)
    treffer = [(text.find(stamm), idx) for stamm, idx in _WOCHENTAG_STAEMME
               if stamm in text]
    return min(treffer)[1] if treffer else 7


def baue_regelmaessig(eintraege, log, personen):
    """Flache Liste regelmaessiger Termine -> sortierte Liste von Anzeige-Dicts.

    Keine Tagesgruppierung wie bei baue_tage() -- ein regelmaessiger Termin
    hat kein datum. Sortiert nach erkanntem Wochentag im rhythmus-Text, dann
    uhrzeit, dann rhythmus, dann titel: stabil und lesbar, ohne die Uhrzeit aus
    Freitext parsen zu muessen (uhrzeit ist seit dem Prompt-Zusatz vom
    16.09.2026 ein eigenes, zuverlaessiges Feld).

    Quellen-Dublettenerkennung UEBER Domains (wie _gruppiere() fuer
    termine.json) findet hier bewusst NICHT statt: _selbes_event() haengt am
    datum, das regelmaessigen Terminen fehlt. Dieselbe Reihe, von zwei Domains
    gemeldet, koennte doppelt erscheinen -- seltener Fall; das Risiko falscher
    Zusammenfuehrungen (aehnliche Titel, verschiedene Orte, ohne Datumsanker)
    waere teurer als diese seltene Dublette.
    """
    gerendert = []
    for t in sorted(eintraege, key=lambda t: (
            _wochentag_index(t.get("rhythmus") or ""),
            t.get("uhrzeit") or "99:99", t.get("rhythmus") or "",
            t.get("titel") or "")):
        slug, var = GENRE_FARBEN.get(t["genre"], GENRE_FARBEN["Sonstiges"])
        gerendert.append({
            "titel": t["titel"], "uhrzeit": t.get("uhrzeit") or "",
            "kuenstler": _mit_person(t.get("kuenstler") or "", t.get("domain"), personen),
            "ort": t.get("ort") or "",
            "beschreibung": t.get("beschreibung") or "",
            "rhythmus": t.get("rhythmus") or "",
            "genre": ANZEIGE_NAME.get(t["genre"], t["genre"]),
            "genre_slug": slug, "genre_farbe": var,
            "link": (link := _link(t, log)), "link_label": _host(link),
        })
    return gerendert


def main():
    zerleger = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    zerleger.add_argument("--spur", default="",
                          help="Namenspraefix fuer Ein- und Ausgabedateien: "
                               "'--spur test' rendert ausgaben/test-termine.json "
                               "nach test-index.html. Ohne Angabe: die "
                               "Produktivdateien")
    argumente = zerleger.parse_args()
    (termine_datei, domain_log_datei, domains_datei, ausgabe,
     regelmaessig_datei) = _pfade(argumente.spur)

    heute = dt.date.today()
    roh = _nur_gueltige(_lade_json(termine_datei, []))
    termine = _gruppiere(roh)
    log = _lade_json(domain_log_datei, {})
    domains = _lade_domains(domains_datei)
    personen = _lade_personen(PERSONEN_DATEI)
    roh_regelmaessig = _nur_gueltige(_lade_json(regelmaessig_datei, []),
                                     _PFLICHT_REGELMAESSIG)
    regelmaessig = baue_regelmaessig(roh_regelmaessig, log, personen)

    genres = [{"name": ANZEIGE_NAME.get(g, g),
               "farbe": GENRE_FARBEN.get(g, GENRE_FARBEN["Sonstiges"])[1],
               "slug": GENRE_FARBEN.get(g, GENRE_FARBEN["Sonstiges"])[0]}
              for g in GENRES]
    tage = baue_tage(termine, log, heute, personen)

    env = Environment(loader=FileSystemLoader(TEMPLATE_ORDNER), autoescape=True,
                      trim_blocks=True, lstrip_blocks=True)
    vorlage = env.get_template("index.html.j2")
    html = vorlage.render(
        genres=genres, days=tage, domains=domains,
        entry_count=len(termine), is_empty=not termine,
        regelmaessig_entries=regelmaessig, regelmaessig_count=len(regelmaessig),
        regelmaessig_is_empty=not regelmaessig,
        generated_at=heute.strftime("%d.%m.%Y"),
    )

    with open(ausgabe, "w", encoding="utf-8") as datei:
        datei.write(html)
    entfernt = len(roh) - len(termine)
    print(f"{len(termine)} Termine"
          + (f" ({len(roh)} vor Gruppierung, {entfernt} Quellen-Dublette(n))"
             if entfernt else "")
          + f", {len(tage)} Tage, {len(regelmaessig)} regelmaessige "
          + f"-> {ausgabe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
