# Orte und Spielstaetten, die als "Freiburg und Umgebung" gelten
#
# nachpruefen() in tools/termine_aus_domain.py verwirft einen Termin, dessen
# `ort` KEINEN dieser Namen enthaelt (Teilstring auf normalisierter Form,
# Gross/Klein egal). Ein Termin ganz ohne Ortsangabe faellt bei
# REGION_LEERER_ORT_OK = False (Vorgabe) ebenfalls raus -- im strengen Modus
# zaehlt nur, was belegbar in der Region liegt.
#
# Fehlt diese Datei, ist der Regionsfilter AUS: eine einzeln kopierte
# termine_aus_domain.py verhaelt sich dann wie zuvor (siehe "EIGENSTAENDIG" im
# Dateikopf). Nur im Projekt, wo die Liste liegt, wird streng gefiltert.
#
# Format wie domains.md: ein Name je Zeile, `#` kommentiert, `##` gliedert nur.
# Von Hand pflegen -- taucht eine neue lokale Spielstaette auf, hier eine Zeile
# ergaenzen, dieselbe Handarbeit wie beim Eintragen einer Domain.

## Stadt Freiburg
Freiburg

## Dreisamtal und Hochschwarzwald
Kirchzarten
Stegen
Oberried
Buchenbach
St. Peter
St. Maergen
St. Märgen
Hinterzarten
Titisee
Neustadt
Breitnau
Feldberg

## Markgraeflerland und suedlicher Breisgau
Merzhausen
Horben
Guenterstal
Günterstal
Wittnau
Bollschweil
Ebringen
Pfaffenweiler
Schallstadt
Ehrenkirchen
Bad Krozingen
Staufen
Muenstertal
Münstertal
Sulzburg
Heitersheim
Buggingen
Muellheim
Müllheim
Neuenburg
Hartheim

## Tuniberg, Kaiserstuhl und westlicher Breisgau
Breisach
Umkirch
Gottenheim
Boetzingen
Bötzingen
Eichstetten
Bahlingen
Nimburg
Ihringen
Merdingen
Vogtsburg
Endingen
Riegel
Sasbach
Kaiserstuhl
Tuniberg

## Noerdlicher Breisgau und Elztal
Gundelfingen
Denzlingen
Voerstetten
Vörstetten
Heuweiler
Glottertal
Waldkirch
Emmendingen
Sexau
Malterdingen
Teningen
Kenzingen
Elzach
Gutach
Simonswald

## Groessere Regionsnamen
Breisgau
Dreisamtal
Kaiserstuhl
Markgraeflerland
Markgräflerland

## Spielstaetten ohne Ortsnamen im Titel
Schopf2
Schopf 2
Waldsee
Ensemblehaus
PAN.OPTIKUM
Panoptikum
Klavierdepot
Vorderhaus
Wallgraben
Marienbad
Lokhalle
Jazzhaus
Paulussaal
Humboldtsaal
E-Werk
Suedufer
Südufer
Depot.K
ArTik
Gruenhof
Grünhof
