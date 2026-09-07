#!/usr/bin/env python3
"""Sammel-Lauf ueber domains.md: scannen, wenn faellig, Funde verschmelzen.

Arbeitsteilung mit termine_aus_domain.py: das dortige Skript konfektioniert
EINEN Aufruf fuer EINE Domain und weiss nichts von Zeit. Dieses hier weiss
nichts vom Modell — es fuehrt Buch darueber, WANN welche Domain zuletzt dran
war, und was ueber mehrere Laeufe hinweg als derselbe Termin gilt. Deshalb
zwei Dateien statt eines --sammellauf-Schalters: termine_aus_domain.py soll
weiter 'EIGENSTAENDIG ... laesst sich woandershin kopieren' bleiben.

    python domain_lauf.py                  # alles Faellige, Vorgabe 7 Tage
    python domain_lauf.py --frische 0      # alles neu scannen, egal wie frisch
    python domain_lauf.py --frische 28     # nur was aelter als vier Wochen ist
    python domain_lauf.py --nur foo.de     # eine Domain, ohne domains.md zu aendern
    python domain_lauf.py --liste x.md     # andere Domain-Liste statt domains.md
    python domain_lauf.py --spur test      # eigenes Gleis: test-domains.md ->
                                           # test-termine.json, test-domain_log.json
    python domain_lauf.py --trocken        # zeigen, was faellig waere, nichts tun

DREI DATEIEN, drei getrennte Aufgaben:

    domains.md        Eingabe, von Hand gepflegt. Eine Domain je Zeile.
    domain_log.json   Buchhaltung: welche Seiten wurden gelesen, wann zuletzt.
                      Wird je Scan ueberschrieben, keine Historie.
    termine.json      Die Funde aller Domains zusammen. Waechst und
                      aktualisiert sich, ist aber KEIN Archiv.

--spur legt allen dreien ein Praefix vor (test-domains.md, test-termine.json,
test-domain_log.json). So laesst sich ein Referenzbestand aufbauen, ohne den
produktiven anzufassen. Das domain_log MUSS mitwandern, siehe _pfade().

VERGANGENES FLIEGT RAUS, auch aus dem Bestand. Warum sollte man es
mitschleppen — die Datei soll zeigen, was noch bevorsteht. Entscheidend ist
das HEUTIGE Datum beim Aufraeumen, nicht das des Laufs, der den Eintrag
geschrieben hat; sonst bliebe ein Termin ewig stehen, der beim Schreiben
noch in der Zukunft lag.

WAS IST DERSELBE TERMIN? Die Frage entscheidet alles beim zweiten Lauf. Der
Titel taugt nicht als Schluessel — er schwankt zwischen Laeufen, mal
'IMPERIA', mal 'IMPERIA ... ein drolldreistes Soloschauspiel' (README, Punkt
3 unter 'Was noch fehlt'). Wer ihn in den Schluessel nimmt, bekommt bei
jedem Rescan Dubletten statt Aktualisierungen.

Deshalb: domain + datum + uhrzeit muessen gleich sein (die drei Felder, die
nachpruefen() ohnehin gegen den Text belegt), und der Titel muss nur
AEHNLICH sein. Bewusst ohne Modellaufruf — ob zwei Zeichenketten dasselbe
meinen, ist Mechanik, keine Urteilsfrage, und eine nicht-deterministische
Dublettenpruefung waere das Letzte, was man hier will.

NICHT GEFUNDEN HEISST NICHT WEG. Ein alter Termin, der beim Rescan fehlt,
aber noch nicht vergangen ist, bleibt stehen. Ein Lauf kann eine Unterseite
verfehlen (Zeichenbudget, Timeout, Umbau der Website) — das darf keine
bereits belegten Termine loeschen.
"""
import argparse
import datetime as dt
import difflib
import json
import os
import sys

import termine_aus_domain as tad

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HIER = os.path.dirname(os.path.abspath(__file__))
PROJEKT = os.path.dirname(HIER)

def _pfade(spur=""):
    """Namenspraefix -> (domains, domain_log, termine, reihen). Leer = Produktion.

    Ein Testlauf soll den Produktivbestand nicht anfassen: '--spur test' liest
    eingaben/test-domains.md und schreibt ausgaben/test-termine.json sowie
    ausgaben/test-domain_log.json.

    Das domain_log MUSS mitwandern. Teilten sich Test- und Produktivlauf eins,
    wuerde ein Testlauf die Domain als 'frisch besucht' eintragen und der
    naechste Produktivlauf sie ueberspringen -- der echte Bestand veraltete,
    ohne dass es auffaellt.

    reihen entsteht nur mit --reihen; ohne den Schalter wird die Datei nicht
    angelegt.
    """
    p = f"{spur}-" if spur else ""
    return (os.path.join(PROJEKT, "eingaben", f"{p}domains.md"),
            os.path.join(PROJEKT, "ausgaben", f"{p}domain_log.json"),
            os.path.join(PROJEKT, "ausgaben", f"{p}termine.json"),
            os.path.join(PROJEKT, "ausgaben", f"{p}reihen.json"))


DOMAINS, DOMAIN_LOG, TERMINE, REIHEN = _pfade()

FRISCHE_TAGE = 7        # juenger als das -> beim Sammellauf ueberspringen
AEHNLICHKEIT = 0.6      # Startwert, nicht gemessen; siehe _aehnlich()


# ------------------------------------------------------------------- Laden

def lade_domains(pfad):
    """domains.md -> [domain, ...]

    Eine Domain je Zeile. Leerzeilen und '#'-Kommentare fallen raus, damit die
    Liste spaeter nach Sparten gegliedert werden kann, ohne dass das Format
    bricht.

    Split auf das erste '#' statt nur startswith(): so bleibt eine Zeile wie
    'foo.de  # Name, Charakter' beim Aktivieren (fuehrendes '#' entfernt,
    Annotation dahinter stehen gelassen) sauber lesbar -- nur 'foo.de' wird
    Domain, der Kommentar faellt weg statt Teil des Domainstrings zu werden.
    Eine Kategorie-Ueberschrift ('## Museen') liefert vor dem ersten '#'
    nichts und faellt weiterhin raus.
    """
    if not os.path.exists(pfad):
        return []
    domains = []
    with open(pfad, encoding="utf-8") as datei:
        for zeile in datei:
            kern = zeile.split("#", 1)[0].strip()
            if kern:
                domains.append(kern)
    return domains


def _lade_json(pfad, vorgabe):
    """Fehlende Datei ist kein Fehler — beim ersten Lauf gibt es sie noch nicht."""
    if not os.path.exists(pfad):
        return vorgabe
    try:
        with open(pfad, encoding="utf-8") as datei:
            return json.load(datei)
    except (json.JSONDecodeError, OSError) as fehler:
        print(f"WARNUNG: {pfad} nicht lesbar ({fehler}) — beginne mit Leerstand.",
              file=sys.stderr)
        return vorgabe


def _schreibe_json(pfad, inhalt):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)  # ausgaben/ bei frischem Checkout
    with open(pfad, "w", encoding="utf-8") as datei:
        json.dump(inhalt, datei, ensure_ascii=False, indent=2)
        datei.write("\n")


# ------------------------------------------------------------------ Frische

def ist_frisch(eintrag, heute, tage):
    """Wurde die Domain vor weniger als 'tage' Tagen besucht? -> bool

    Ein unlesbares oder fehlendes Besuchsdatum gilt als 'nicht frisch'. Im
    Zweifel wird gescannt: ein ueberfluessiger Scan kostet zwei Cent, ein
    ausgelassener kostet die Termine.
    """
    if not eintrag:
        return False
    try:
        besucht = dt.date.fromisoformat(eintrag.get("besucht", ""))
    except (ValueError, TypeError):
        return False
    return (heute - besucht).days < tage


# ------------------------------------------------------- Derselbe Termin?

def _aehnlich(a, b):
    """Zwei Titel -> bool. Ueber _normal() aus termine_aus_domain.

    Zwei Stufen, und die erste erledigt den einzigen Fall, der bisher
    tatsaechlich beobachtet wurde: 'IMPERIA' gegen 'IMPERIA ... ein
    drolldreistes Soloschauspiel' — derselbe Titel, einmal gekuerzt. Ein
    Teilstring-Test faengt das, ohne Schwellenwert.

    Die zweite Stufe (SequenceMatcher) ist fuer Umformulierungen, die noch
    keiner gesehen hat. AEHNLICHKEIT bewusst nicht niedriger: lieber eine
    Dublette in der Liste als zwei echte Termine faelschlich verschmolzen.
    Eine Dublette sieht man und raeumt sie weg, ein verlorener Termin faellt
    niemandem auf.
    """
    na, nb = tad._normal(a), tad._normal(b)
    if not na or not nb:
        return na == nb
    if na in nb or nb in na:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= AEHNLICHKEIT


def gleicher_termin(alt, neu):
    """Bezeichnen zwei Eintraege dieselbe Veranstaltung? -> bool

    Datum und Uhrzeit muessen exakt stimmen; sie sind die einzigen Felder,
    die nachpruefen() gegen den Seitentext belegt hat. Der Titel darf
    abweichen, solange er aehnlich bleibt.
    """
    return (alt.get("domain") == neu.get("domain")
            and alt.get("datum") == neu.get("datum")
            and (alt.get("uhrzeit") or "") == (neu.get("uhrzeit") or "")
            and _aehnlich(alt.get("titel"), neu.get("titel")))


def verschmelze(bestand, neue, domain, heute):
    """Bestand + frische Funde einer Domain -> neuer Bestand.

    Drei Regeln, in dieser Reihenfolge:

    1. Was vergangen ist, faellt raus — aus beidem, Bestand wie Fund.
    2. Ein neuer Fund, der zu einem alten Eintrag passt, ERSETZT ihn. Die
       frische Fassung gewinnt: sie kommt von der Seite, wie sie heute
       aussieht.
    3. Ein alter Eintrag ohne frische Entsprechung bleibt stehen (siehe
       Kopf: nicht gefunden heisst nicht weg).

    Eintraege anderer Domains laufen unangetastet durch — nur die vergangenen
    verschwinden, damit ein Sammellauf die ganze Datei aufraeumt und nicht
    nur den gerade gescannten Teil.
    """
    kuenftig = [t for t in bestand if t.get("datum", "") >= heute.isoformat()]
    fremd = [t for t in kuenftig if t.get("domain") != domain]
    eigen = [t for t in kuenftig if t.get("domain") == domain]

    frisch = []
    for fund in neue:
        if fund.get("datum", "") < heute.isoformat():
            continue
        eintrag = dict(fund)
        eintrag["domain"] = domain
        frisch.append(eintrag)

    behalten = [alt for alt in eigen
                if not any(gleicher_termin(alt, neu) for neu in frisch)]

    zusammen = fremd + behalten + frisch
    return sorted(zusammen, key=lambda t: (t.get("datum", ""),
                                           t.get("uhrzeit") or "",
                                           t.get("domain", "")))


def verschmelze_reihen(bestand, neue, domain):
    """Bestand + frische Reihen einer Domain -> neuer Bestand.

    UMGEKEHRTE REGEL gegenueber verschmelze(). Dort gilt "nicht gefunden heisst
    nicht weg", weil ein Termin ein Datum hat, an dem er von selbst verfaellt.
    Eine Reihe hat keins. Sie kann nur dadurch enden, dass sie von der Seite
    verschwindet -- bliebe sie trotzdem stehen, stuende der Meditationskreis
    noch Jahre nach seiner letzten Sitzung im Bestand.

    Die Reihen der Domain werden deshalb vollstaendig ERSETZT. Das ist sicher,
    weil scanne() bei Fehlschlag None liefert und dieser Weg dann gar nicht
    beschritten wird: ein misslungener Abruf loescht nichts.

    Eintraege anderer Domains laufen unangetastet durch.
    """
    fremd = [r for r in bestand if r.get("domain") != domain]
    frisch = [dict(r, domain=domain) for r in neue]
    return sorted(fremd + frisch, key=lambda r: (r.get("domain", ""),
                                                 r.get("rhythmus", ""),
                                                 r.get("uhrzeit") or ""))


# -------------------------------------------------------------------- Lauf

def scanne(domain, heute, modell, variante="einzeln"):
    """Eine Domain -> (termine, reihen, seiten) oder (None, None, []) bei Misserfolg.

    Nutzt termine_aus_domain unveraendert: dieselbe Seitenauswahl, derselbe
    Modellaufruf, dieselbe Belegpruefung wie beim Einzelaufruf.

    reihen ist bei der Variante "einzeln" immer leer -- dort fragt der Auftrag
    gar nicht danach.
    """
    print("  ...ruft Seiten ab")
    try:
        text, quelle, gelesen = tad.sammle_seiten(domain, heute, None)
    except Exception as fehler:
        # str() statt nur Typname: social_holen.BrowserNichtErreichbar traegt den
        # Hinweis "chrome-debug.cmd starten" in der Meldung; ein blosses
        # "BrowserNichtErreichbar" hilft niemandem. Domain bleibt faellig.
        hinweis = str(fehler) if fehler.args else type(fehler).__name__
        print(f"  nicht erreichbar: {hinweis}")
        return None, None, []

    gekappt = text[:tad.MAX_ZEICHEN]
    print(f"  ...fragt claude ({len(gelesen)} Seite(n), {len(gekappt)} Zeichen)")
    inhalt, kennzahlen = tad.claude_fragen(gekappt, heute, modell, variante)
    if inhalt is None:
        print("  claude lieferte keine Antwort")
        return None, None, [adresse for adresse, _ in gelesen]

    funde = inhalt.get("termine", [])
    seiten = [a for a, _ in gelesen]
    ort_pflicht = tad.ist_tour(domain)
    gut, verworfen, _ = tad.nachpruefen(funde, gekappt, heute,
                                        seiten=seiten, ort_pflicht=ort_pflicht)
    reihen, reihen_verworfen = tad.pruefe_reihen(inhalt.get("reihen"), gekappt,
                                                 seiten=seiten,
                                                 ort_pflicht=ort_pflicht)
    # Vergangene getrennt ausweisen, sonst steht am Ende '4 uebernommen' neben
    # '1 im Bestand' und niemand weiss, wo die anderen drei geblieben sind.
    vorbei = len([t for t in gut if t.get("datum", "") < heute.isoformat()])
    print(f"  {len(gelesen)} Seite(n), "
          f"{len(funde) + len(inhalt.get('reihen') or [])} gemeldet, "
          f"{len(gut)} uebernommen"
          + (f" (davon {vorbei} vorbei)" if vorbei else "")
          + (f", {len(reihen)} regelmaessig" if reihen else "")
          + f", {len(verworfen) + len(reihen_verworfen)} verworfen, "
          f"{kennzahlen.get('kosten', 0.0):.4f} USD")
    return gut, reihen, seiten


def main():
    zerleger = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    zerleger.add_argument("--frische", type=int, default=FRISCHE_TAGE,
                          help=f"Tage, die ein Scan als frisch gilt "
                               f"(Vorgabe: {FRISCHE_TAGE}; 0 = alles neu scannen)")
    zerleger.add_argument("--nur", default="",
                          help="nur diese eine Domain, statt domains.md")
    zerleger.add_argument("--liste", default=None,
                          help="andere Domain-Liste statt eingaben/domains.md "
                               "(z. B. eingaben/test-domains.md); gleiches Format. "
                               "Gewinnt gegen --spur")
    zerleger.add_argument("--spur", default="",
                          help="Namenspraefix fuer ALLE Ein- und Ausgabedateien: "
                               "'--spur test' liest eingaben/test-domains.md und "
                               "schreibt ausgaben/test-termine.json und "
                               "ausgaben/test-domain_log.json. Ohne Angabe: "
                               "die Produktivdateien")
    zerleger.add_argument("--modell", default="haiku",
                          help="Modell fuer claude -p (Vorgabe: haiku)")
    zerleger.add_argument("--trocken", action="store_true",
                          help="nur zeigen, was faellig waere; nichts scannen, "
                               "nichts schreiben")
    zerleger.add_argument("--reihen", action="store_true",
                          help="regelmaessige Termine ('immer dienstags') als "
                               "zweite Liste mitnehmen, nach "
                               "ausgaben/reihen.json. BEFRISTET, siehe "
                               "VARIANTEN in termine_aus_domain")
    argumente = zerleger.parse_args()

    heute = dt.date.today()
    variante = "reihen" if argumente.reihen else "einzeln"
    domains_datei, domain_log_datei, termine_datei, reihen_datei = _pfade(argumente.spur)
    if argumente.liste:                  # explizit gesetzt -> gewinnt gegen --spur
        domains_datei = argumente.liste

    domains = [argumente.nur] if argumente.nur else lade_domains(domains_datei)
    if not domains:
        print(f"Keine Domains. {domains_datei} fehlt oder ist leer.", file=sys.stderr)
        return 1

    log = _lade_json(domain_log_datei, {})
    bestand = _lade_json(termine_datei, [])
    reihen_bestand = _lade_json(reihen_datei, []) if argumente.reihen else []

    faellig = [d for d in domains
               if not ist_frisch(log.get(d), heute, argumente.frische)]
    print(f"{len(domains)} Domain(s), {len(faellig)} faellig "
          f"(Frische: {argumente.frische} Tage)\n")

    if argumente.trocken:
        for domain in domains:
            eintrag = log.get(domain)
            zuletzt = (eintrag or {}).get("besucht", "nie")
            zustand = "faellig" if domain in faellig else "frisch"
            print(f"  {zustand:<8} {domain:<32} zuletzt: {zuletzt}")
        return 0

    gescannt = 0
    for domain in faellig:
        print(f"{domain}")
        termine, reihen, seiten = scanne(domain, heute, argumente.modell, variante)
        if termine is not None:
            bestand = verschmelze(bestand, termine, domain, heute)
            if argumente.reihen:
                reihen_bestand = verschmelze_reihen(reihen_bestand, reihen, domain)
            log[domain] = {"seiten": seiten,   # seiten[0] ist die Adresse nach Weiterleitung
                           "besucht": heute.isoformat()}
            gescannt += 1
        # Nach JEDER Domain schreiben, nicht erst am Ende der Schleife -- bei
        # Abbruch (Ctrl-C, Absturz, Timeout) bleibt so der Fortschritt aller
        # bereits fertigen Domains erhalten. Bei Fehlschlag unveraendert,
        # der Schreibvorgang ist dann nur redundant, nicht falsch.
        _schreibe_json(domain_log_datei, log)
        _schreibe_json(termine_datei, bestand)
        if argumente.reihen:
            _schreibe_json(reihen_datei, reihen_bestand)

    # Auch ohne einen einzigen Scan aufraeumen: Vergangenes soll verschwinden,
    # sobald jemand den Lauf startet, nicht erst wenn zufaellig eine Domain
    # faellig ist.
    vorher = len(bestand)
    bestand = [t for t in bestand if t.get("datum", "") >= heute.isoformat()]
    entfernt = vorher - len(bestand)

    _schreibe_json(domain_log_datei, log)
    _schreibe_json(termine_datei, bestand)
    if argumente.reihen:
        _schreibe_json(reihen_datei, reihen_bestand)

    print(f"\n{gescannt} gescannt, {len(bestand)} Termine im Bestand"
          + (f", {len(reihen_bestand)} Reihen" if argumente.reihen else "")
          + (f", {entfernt} vergangene entfernt" if entfernt else ""))
    print(f"-> {termine_datei}\n-> {domain_log_datei}"
          + (f"\n-> {reihen_datei}" if argumente.reihen else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
