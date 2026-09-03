# Test-Domains — kleiner Satz zum schnellen Iterieren
#
# Jede Domain hier reizt einen anderen Code-Pfad oder eine andere Fehlerklasse
# aus. Statt des ganzen eingaben/domains.md nur diese hier laufen lassen:
#
#     domain_lauf --liste eingaben/test-domains.md --frische 0
#
# Format wie domains.md: eine Domain je Zeile, `#` kommentiert; ein `#` hinter
# einer Domain schneidet lade_domains() ab, die Anmerkung darf stehen bleiben.

## Konzert
mehrklang-freiburg.de        # Mehrseiten-Crawl (events + 2 Kategorien), fundstelle, viele Konzerte
#murat-coskun.eu              # Freiburger Kuenstler auf Tour -> Regionsfilter (Pilsen/Strassburg muessen raus)
ensemble-recherche.de        # meldet dasselbe Ensemble-Akademie-Konzert wie mehrklang + barockorchester
barockorchester.de           # dritte Quelle desselben Konzerts -> prueft _gruppiere() in baue_webseite.py
kloster-st-lioba.de          # Genre "Spirituell"; Ort "Freiburg-Guenterstal" prueft den Regionsfilter mit Ortsteilnamen

## Theater
klavierdepot-freiburg.de     # Weiterleitung auf petra-gack.de/klavierdepot, genau 1 Termin

## Kulturraum
kreativpioniere-freiburg.de  # nicht-deterministisch (5-8 Treffer), Quelle des _nur_gueltige()-Bugs, _tage_vor_monat()
stiftung-konkrete-kunst.de   # NEGATIV-ANKER: hier entstanden die 9 Geistervernissagen aus einer Ausstellungsdauer.
                             # Prueft Zeitraum-nicht-aufloesen (Prompt), Datumsbeleg (nachpruefen) und den
                             # Jahresarchiv-Filter (veranstaltungen_1999_2000.html ... _2025.html)
#schopf2.de                   # reiner Veranstaltungsort, Ausbeute nahe null (Negativprobe)

## Tanz (und Performance)
instagram.com/betz.lucie/    # social_holen.py / Browser-Pfad, /p/<shortcode>/-Links

