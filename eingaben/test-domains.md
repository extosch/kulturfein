# Test-Domains — kleiner Satz zum schnellen Iterieren
#
# Fuenf Domains, die je einen anderen Code-Pfad ausreizen. Statt des ganzen
# eingaben/domains.md nur diese hier laufen lassen:
#
#     domain_lauf --liste eingaben/test-domains.md --frische 0
#
# Format wie domains.md: eine Domain je Zeile, `#` kommentiert; ein `#` hinter
# einer Domain schneidet lade_domains() ab, die Anmerkung darf stehen bleiben.

## Konzert
mehrklang-freiburg.de        # Mehrseiten-Crawl (events + 2 Kategorien), fundstelle, viele Konzerte
murat-coskun.eu              # Freiburger Kuenstler auf Tour -> Regionsfilter (Pilsen/Strassburg muessen raus)

## Theater
klavierdepot-freiburg.de     # Weiterleitung auf petra-gack.de/klavierdepot, genau 1 Termin

## Kulturraum
kreativpioniere-freiburg.de  # nicht-deterministisch (5-8 Treffer), Quelle des _nur_gueltige()-Bugs, _tage_vor_monat()
#schopf2.de                   # reiner Veranstaltungsort, Ausbeute nahe null (Negativprobe)

## Tanz (und Performance)
instagram.com/betz.lucie/    # social_holen.py / Browser-Pfad, /p/<shortcode>/-Links

