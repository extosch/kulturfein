# Geschlossene Liste moeglicher Genres. Ohne Aufzaehlung erfindet das Modell
# Kategorien wie "Musiktheater", und die Auswertung zerfaellt.
#
# Umlaute ASCII-sicher umschreiben (z.B. "Spirituell" statt Woertern mit
# "ö"/"ü") -- die Liste geht als Teil von --json-schema ueber die Windows-
# Kommandozeile, Umlaute dort sind riskant.
#
# Optional: fehlt diese Datei, greift der eingebaute Standard in
# termine_aus_domain.py (dieselben neun Werte). Nur wenn sie danebenliegt,
# wird die Liste editierbar -- Kopierbarkeit des Skripts bleibt erhalten.
Konzert
Lesung
Spirituell
Tanz
Workshop
Buehne         # Theater, Kleinkunst, Kabarett, Performance, Figurentheater. Anzeige "Buehne" -> "Bühne" in baue_webseite.py (ASCII-Wert wegen --json-schema)
Ausstellung    # kunstbezogener PUNKT-Termin: Vernissage, Finissage, Kuenstlergespraech, Fuehrung. NICHT die Ausstellungsdauer -- die bleibt "kein Termin" (Prompt)
Vortrag
Sonstiges