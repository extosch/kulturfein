# kulturfein

## Überblick

**Eingabe** — von Hand gepflegt

| Datei | Rolle |
|---|---|
| [`eingaben/domains.md`](eingaben/domains.md) | Domainliste, eine je Zeile, `#` für Kommentare, nach Ortskategorien aus `spielstaetten.md` gegliedert |
| [`eingaben/region.md`](eingaben/region.md) | Orte und Spielstätten, die als „Freiburg und Umgebung" gelten. Optional — **fehlt sie, ist der Regionsfilter aus**; liegt sie vor, verwirft `nachpruefen()` jeden Termin außerhalb |
| [`eingaben/test-domains.md`](eingaben/test-domains.md) | Kleiner Domain-Satz zum Debuggen, je Domain ein anderer Code-Pfad. `domain_lauf --liste eingaben/test-domains.md` |
| [`tools/genres.md`](tools/genres.md) | Geschlossene Genre-Liste. Optional — fehlt sie, greift ein eingebauter Standard in `termine_aus_domain.py`. Bewusst **nicht** in `eingaben/`, siehe unten |

**Skripte** — in [`tools/`](tools/)

| Datei | Zweck | Aufruf |
|---|---|---|
| `termine_aus_domain.py` | eine Domain → Termine | `termine_aus_domain foo.de` |
| `domain_lauf.py` | `eingaben/domains.md` abarbeiten, Buchhaltung führen | `domain_lauf` |
| `baue_webseite.py` | `ausgaben/termine.json` → `index.html` | `baue_webseite` |
| `social_holen.py` | Instagram-Profile über einen Chrome lesen (optional, von `termine_aus_domain.py` genutzt; startet den Browser bei Bedarf selbst) | — |
| `chrome-debug.cmd` | optional: angemeldeter Chrome mit Debug-Port, für private Profile / mehr Zuverlässigkeit | — |
| `archiv/termine_aus_domain_via_claude_webfetch.py` | geparkter Gegenversuch, nicht aktiv genutzt | — |

**Generiert** — entsteht beim Lauf, nicht von Hand anfassen

| Datei | Inhalt |
|---|---|
| `ausgaben/domain_log.json` | je Domain: welche Seiten gelesen, wann zuletzt |
| `ausgaben/termine.json` | alle gefundenen Termine, dedupliziert, kein Archiv |
| `index.html` | die gerenderte Webseite — bewusst am Root, nicht in `ausgaben/`, für ein mögliches späteres Hosting (GitHub Pages & Co. erwarten sie dort oder in `docs/`) |

Alle drei Skripte haben zusätzlich einen `.cmd`-Wrapper für PowerShell/cmd
(`termine_aus_domain.cmd`, `domain_lauf.cmd`, `baue_webseite.cmd`) neben der Git-Bash-Fassung,
alle in `C:\Users\info\.local\bin`. Details zu jedem Schritt weiter unten.

---

Angelegt am 2026-08-26. **Ein Werkzeug, ein Zweck:** eine Domain hineingeben, klassifizierte
Termine als JSON herausbekommen.

```
termine_aus_domain klavierdepot-freiburg.de
```

Das war der Anfang, und der Einzelaufruf bleibt der Kern. **Seit dem 31.08.2026 gibt es eine
Stammliste** — `domains.md`, abgearbeitet von [`tools/domain_lauf.py`](tools/domain_lauf.py),
das Buch führt, wann welche Domain zuletzt dran war und Funde über Läufe hinweg verschmilzt.
Sie kam erst, als der eine Aufruf belegbar trug: vier durchgemessene Fälle, drei gefundene
und behobene Fehler in der Nachprüfung. Eine Ampel gibt es weiterhin nicht.

Eine Heuristik ist inzwischen doch dabei, aber an anderer Stelle als beim Vorgänger: sie
**wählt Seiten aus**, sie **liest keine Termine**. Welche Unterseite gelesen wird, entscheidet
ein Punkteschema; was darin ein Termin ist, entscheidet weiterhin allein das Modell.

---

## Warum nicht wie der Vorgänger

Das Vorgängerprojekt (`../my_first_ai_coding_tests/kuenstlerradar_old/`) las Termine mit einer Kaskade aus JSON-LD,
Microdata, iCal und DOM-Heuristik. Wo die versagte, sprang ein Sprachmodell ein — über
`claude -p`, mit der vollen Claude-Code-Umgebung im Rücken.

Genau das war der Fehler. Eine Messreihe am 26.08.2026 zeigte, wofür dabei bezahlt wurde:

| Konfiguration | Kontext je Aufruf |
|---|---:|
| interaktive Sitzung im Projektordner | 43.300 Token |
| davon Werkzeugbeschreibungen | 23.800 |
| davon Claude-Code-Systemprompt | 5.200 |
| davon Projekt-`CLAUDE.md` | 4.700 |
| davon globale `~/.claude/CLAUDE.md` | 1.300 |
| **der eigentliche Seitentext** | **~450** |

Ein Prozent Nutzlast. Der Rest ist Ausrüstung für einen Programmier-Agenten, die beim
Abschreiben von Terminen aus einem Fließtext nichts beiträgt.

---

## Was das Skript anders macht

[`tools/termine_aus_domain.py`](tools/termine_aus_domain.py) baut den Kontext **selbst** und
lässt nichts Automatisches zu. Vier Vorkehrungen:

| | wirkt gegen |
|---|---|
| `--tools ""` | die 23.800 Token Werkzeugbeschreibungen |
| `--system-prompt TEXT` | die 5.200 Token Claude-Code-Systemprompt |
| `cwd` in einem leeren Temp-Ordner | die 4.700 Token Projekt-`CLAUDE.md` |
| `MAX_THINKING_TOKENS=0` | das Nachdenken |

Gemessen am selben Fall, dem Klavierdepot Freiburg:

| | Vorgänger (`find_dates_in_page.py`) | dieses Skript |
|---|---:|---:|
| Eingabe | 12.403 Token | **2.897** |
| Ausgabe | 3.693 Token | **263** |
| Kosten | 0,0448 $ | **0,0062 $** |
| Termine | 4 | 4 |
| Abhängigkeiten | 3 Projektmodule | keine |

### Die überraschendste Zeile ist die vierte

Das Abschalten des Nachdenkens war als Sparmaßnahme gedacht. Gemessen, gleicher Text,
gleicher Auftrag:

| | Denk-Token | Kosten | **gefundene Termine** |
|---|---:|---:|---:|
| ohne Dämpfung | 11.049 | 0,0606 $ | **2** |
| `--effort low` | 5.248 | 0,0316 $ | **2** |
| `MAX_THINKING_TOKENS=0` | **0** | **0,0058 $** | **4** |

Das Grübeln kostete das Zehnfache **und halbierte die Trefferquote**. Termine aus einem Text
abzuschreiben ist keine Denkaufgabe; wer das Modell dazu bringt, darüber nachzudenken,
bekommt Interpretation statt Abschrift. `--effort` greift bei Haiku 4.5 nur halb — die
Umgebungsvariable schaltet es ganz ab.

---

## Aufruf

Zwei Schalter, die einander nicht kennen: **`--json` sagt wie, `--out` sagt wohin.**

| | stdout | Datei |
|---|---|---|
| **lesbar** | `termine_aus_domain foo.de` | `termine_aus_domain foo.de --out x.txt` |
| **JSON** | `termine_aus_domain foo.de --json` | `termine_aus_domain foo.de --json --out x.json` |

Ohne `--out` wird nichts geschrieben. Weitere Schalter:

```
termine_aus_domain foo.de --modell sonnet      # statt haiku
termine_aus_domain foo.de --show-prompt        # den an claude uebergebenen Prompt auf stderr
termine_aus_domain foo.de --verbose            # Abruf und Datumsbelege auf stderr
termine_aus_domain https://x.de/programm       # statt einer Domain eine volle Adresse
```

Der Fehlerfall nimmt denselben Weg wie der Erfolg — `--json --out` liefert auch dann
gültiges JSON, mit `"fehler"` statt Terminen. Der Hinweis auf die geschriebene Datei geht
auf stderr, damit Pipes sauber bleiben.

### Von überall aufrufbar

In `C:\Users\info\.local\bin` (liegt im `PATH`) stehen Wrapper, je Skript zwei — einer für
PowerShell/cmd (`.cmd`), einer für Git Bash (das erkennt `.cmd` nicht ohne Endung). Namen
folgen exakt dem jeweiligen Dateinamen, damit auf einen Blick klar ist, was zu was gehört:

| Skript | Wrapper |
|---|---|
| `tools/termine_aus_domain.py` | `termine_aus_domain` / `termine_aus_domain.cmd` |
| `tools/domain_lauf.py` | `domain_lauf` / `domain_lauf.cmd` |
| `tools/baue_webseite.py` | `baue_webseite` / `baue_webseite.cmd` |

Wandert eines der Skripte, müssen die zugehörigen zwei Wrapper nachgezogen werden.

---

## Ausgabeformat

```json
{
  "ziel": "stiftung-konkrete-kunst.de",
  "quelle": "https://stiftung-konkrete-kunst.de/",
  "abgerufen": "2026-08-26",
  "termine": [
    {"datum": "2026-11-08", "uhrzeit": "11:30",
     "titel": "Nurit Stark, Violine", "kuenstler": "Nurit Stark",
     "ort": "", "beschreibung": "", "genre": "Konzert"}
  ],
  "seiten": [
    {"adresse": "https://stiftung-konkrete-kunst.de/", "zeichen": 1976},
    {"adresse": "https://stiftung-konkrete-kunst.de/veranstaltungen/veranstaltungen_2026.html",
     "zeichen": 2074},
    {"adresse": "https://stiftung-konkrete-kunst.de/ausstellungen/ausstellungen_2026.html",
     "zeichen": 1862}
  ],
  "gemeldet": 6, "verworfen": 0, "zeichen": 6126,
  "kosten_usd": 0.0168,
  "tokens": {"ein": 4978, "aus": 425}
}
```

`quelle` ist die Adresse **nach** Weiterleitungen. Beim Klavierdepot ist das
`petra-gack.de/klavierdepot` — ohne diese Angabe wäre kein Fund nachprüfbar.

`seiten` führt auf, was tatsächlich gelesen wurde, mit Umfang. Die Startseite steht immer an
erster Stelle. Das Feld ist die Antwort auf „woher kommt dieser Fund?" — und die Angabe, auf
der ein späterer Speicher aufsetzen müsste, der sich die Terminseite einer Domain merkt,
statt sie bei jedem Lauf neu zu erraten.

`genre` stammt aus einer **geschlossenen** Liste, seit 31.08.2026 in
[`tools/genres.md`](tools/genres.md) statt hartcodiert im Skript:

```
Tanz | Bühne | Vortrag | Spirituell | Ausstellung |
Konzert | Lesung | Workshop | Sonstiges
```

`Bühne` (Theater, Kleinkunst, Kabarett, Performance) steht als ASCII-Wert `Buehne` in
`genres.md` — die Liste geht als `--json-schema` an `claude`, Umlaute im Wert sind riskant;
`baue_webseite.py` zeigt „Bühne" über `ANZEIGE_NAME`. `Ausstellung` ist ein **Punkt**-Termin
(Vernissage, Finissage, Künstlergespräch, Führung), nicht die Ausstellungsdauer — die bleibt
„kein Termin".

Fehlt `genres.md` (z. B. weil nur `termine_aus_domain.py` allein kopiert wurde,
siehe „EIGENSTAENDIG" im Dateikopf), greift ein eingebauter Standard mit
denselben neun Werten — die Datei macht die Liste editierbar, ist aber keine
Voraussetzung fürs Laufen. `baue_webseite.py` bricht bei einem in `genres.md` neu
hinzugefügten Wert ohne zugehörige Farbe nicht ab, sondern warnt auf stderr
und fällt auf die `Sonstiges`-Farbe zurück.

Diese Liste ist **nicht** dasselbe wie die Kategorien in `domains.md`
(Galerien, Museen, Theater und Bühnen, …, aus `spielstaetten.md`). Erstere
beschreibt einen **Termin**, verifiziert gegen den Text; Letztere schätzt
einen **Ort** vorab ein. Die Stiftung für Konkrete Kunst ist „Galerie" *und*
hat schon Konzert- *und* Ausstellungs-Termine geliefert — eine gemeinsame
Liste würde das verdecken.

`kuenstler`, `ort` und `beschreibung` kamen am 30./31.08.2026 dazu, angelehnt an drei reale Vergleichs-
Listings (Chilli-Magazin, bz-Ticket, WordPress-Eventkalender). `kuenstler` und `ort` sind
kurze Eigennamen und werden wie der Titel wortgetreu gegen den Text geprüft — das
**Faktenrückgrat**. Nennt `kuenstler` mehrere (`Lucie Betz, Miku Arizono`) und steht der
ganze String nicht so im Text, wird jeder Name **einzeln** geprüft und die bestätigten
werden wieder zusammengesetzt — sonst fiele bei jeder Doppelnennung das ganze Feld weg. `beschreibung` ist dagegen eine vom Modell formulierte **Zusammenfassung**
(≤ 150 Zeichen, ganze Sätze): ein wörtlicher Vergleich hatte reihenweise brauchbare Sätze
verworfen (bei `mehrklang-freiburg.de` 6 von 7), ein „nah am Wortlaut"-Prompt dagegen die
Besetzung verdreht (Butoh-Tänzerin „am E-Piano"). Jetzt fasst `beschreibung` nur zusammen,
**was** die Veranstaltung ist — Art, Thema, Anlass, Rahmen —, **keine Namen und keine
Instrumente**; wer auftritt, steht in `kuenstler`. Ohne Instrumenten-Slot lässt sich keine
Besetzung falsch zuordnen. Automatisch geprüft wird nur die **Wortdeckung** als Untergrenze —
mindestens 60 % der Inhaltswörter (ab 4 Buchstaben) im Seitentext —, das fängt frei
Erfundenes ab. Gekürzt wird auf `BESCHREIBUNG_MAX` an der Wortgrenze (mit `…`).
Anders als beim Titel führt ein Fehlschlag hier nicht zum Verwerfen des Termins: ein
unbestätigtes Nebenfeld fällt auf leer zurück (mit `--verbose` als Zeile auf stderr), der
Termin selbst bleibt. `kuenstler` meint, **wer auftritt** — Person oder Ensemble, nicht den
Veranstalter und nicht den Komponisten; ohne diese Abgrenzung im Prompt füllt das Modell das
Feld mit dem Hausnamen.

`fundstelle` (seit 31.08.2026) ist die **konkrete Unterseite**, auf der der Termin steht —
zum Anklicken für Details, weiteren Text oder ein Ticketformular. `<a href>`-Adressen gehen
in `_lies()` verloren, aber jeder Seitenabschnitt im Blob trägt schon eine Zeile
`--- <adresse> ---`; das Modell kopiert die passende. `nachpruefen()` verwirft eine
`fundstelle`, die nicht unter den tatsächlich gelesenen Seiten ist. Fehlt sie, fällt
`baue_webseite.py` auf `domain_log.json → seiten[0]` (Domain-Startseite) zurück. Bei
Instagram ist die `fundstelle` der konkrete `/p/<shortcode>/`-Post.

### Regelmäßige Termine (zweite Liste)

Eine Veranstaltung, die „immer dienstags, 18:00 – 19:30 Uhr" stattfindet, hat **kein
Datum**. Sie fiel bis zum 07.09.2026 doppelt durch: der Prompt verbot sie, und
`nachpruefen()` hätte sie nicht belegen können, weil es nichts zu belegen gibt. Damit
fehlten Meditationskreise, Gottesdienste, offene Proben.

Der Anker wechselt deshalb vom Datum auf die **Regel**: `rhythmus` trägt den
Wiederholungstext wörtlich von der Seite und wird zweistufig geprüft wie sonst der Titel.
Steht er dort nicht, hat das Modell formuliert statt abgeschrieben, und der Eintrag fällt.
Alle übrigen Felder und Prüfungen sind dieselben wie beim Termin (`_nebenfelder()`).

Die Abgrenzung ist die heikle Stelle, und sie hat zwei Seiten:

- **Ausgeschriebene Einzeldaten bleiben Einzeltermine**, auch mehrere für dieselbe
  Veranstaltung. Der „Sonntagskaffee" bei Kloster St. Lioba mit drei genannten Daten wird
  nicht zur Reihe zusammengefasst — das wäre eine Ableitung des Modells, kein Textbeleg.
- **Öffnungszeiten sind kein regelmäßiger Termin.** Eine Ausstellung, die sonntags geöffnet hat, findet
  nicht sonntags statt. Der Satz steht ausdrücklich im Prompt, und das Verbot, einen
  Zeitraum aufzulösen, bleibt wörtlich erhalten.

**Wie das eingeführt wurde — und warum die Weiche wieder weg ist.** Der Prompt war über
Wochen an Einzelfällen gehärtet; ihn zu ersetzen hätte 100 brauchbare Termine aufs Spiel
gesetzt. Der gefährlichste Ausgang wäre kein Fehler gewesen, sondern eine Verschiebung: das
Modell sortiert Termine, die es vorher einzeln lieferte, in die neue Liste — die füllt sich,
`termine.json` wird ärmer, und das sieht wie Erfolg aus.

Deshalb liefen vom 07. bis 09.09.2026 **zwei Prompt-Fassungen parallel**, die alte als
Vorgabe, umschaltbar über `--termine-regelmaessig`. Dazu setzte `--vergleich` beide auf
**denselben** Seitentext an (zwei Modellaufrufe, ein Abruf) — genau dafür saß die Weiche im
Code und nicht in zwei Git-Ständen: nur so fällt die Änderung der Website zwischen zwei
Läufen als Störgröße weg. Solange gemessen wurde, waren `auftrag()` und `SCHEMA` der alten
Fassung nachweislich **byte-identisch** mit dem Stand davor, sonst hätte man nicht die
Prompt-Differenz verglichen, sondern einen Umbau.

Nach der Messung ist die alte Fassung **gelöscht** worden, samt `VARIANTEN` und beiden
Schaltern. Das war von Anfang an so geplant: zwei Prompt-Fassungen driften auseinander,
sobald jemand nur eine härtet, und dann vergleicht man irgendwann zwei zufällige Stände
statt alt gegen neu. Der heutige `auftrag()` ist wortgleich mit der gemessenen Fassung — die
Zahlen unten gelten also unverändert.

Gemessen am 07.09.2026, je zwei Aufrufe auf identischem Text:

| Domain | alte Fassung | neue | davon regelm. | verschoben |
|---|---:|---:|---:|---|
| tibet-kailash-haus.de | 10 | 10 | **8** | – |
| kloster-st-lioba.de | 48 | 63 | 0 | – |
| buddhistisches-zentrum-freiburg.de | 58 | 58 | 0 | – |
| ensemble-recherche.de | 7 | 12 | 0 | – |
| kreativpioniere-freiburg.de | 8 | 9 | 0 | – |
| sternensee-band.de | 8 | 9 | 0 | – |
| mehrklang-freiburg.de | 7 | 7 | 0 | – |
| stiftung-konkrete-kunst.de | 6 | 6 | 0 | – |
| klavierdepot-freiburg.de | 4 | 4 | 0 | – |

**Kein einziger Termin ist zu einem regelmäßigen geworden** — die befürchtete Verschiebung, bei der
sich die neue Rubrik füllt, während `termine.json` ärmer wird, ist nicht eingetreten. Die
Differenzen sind durchweg die bekannte Titellängen-Schwankung („Klang der Stille" gegen
„Klang der Stille Live-Klangreise mit Klangschalen und Bansuri-Flöte").

Die vielen Nullen sind **kein Versagen**: eine Textsuche nach Wiederholungsmustern zeigt,
dass diese Seiten kaum Wiederholungsregeln enthalten. Bei `kloster-st-lioba.de` ist die einzige
Fundstelle „Sonntagskaffee" — ein Eigenname, kein Rhythmus.

Die harte Probe steht bei `tibet-kailash-haus.de`, weil dort **beides** vorkommt: „immer
dienstags, 18:00 – 19:30 Uhr" (echte Reihe) und „Der Tibet-Shop ist montags, mittwochs und
freitags von 15:00 bis 18:00 Uhr geöffnet" (Öffnungszeit). Die acht gefundenen Einträge sind
Meditationen, Puja und Singkreis; Shop und Garten-Café sind nicht dabei.

Ein Einzellauf beweist dabei nichts: `sternensee-band.de` lieferte im ersten Durchgang 7
gegen 1 Termin, im zweiten 8 gegen 9. Deshalb verglich `--vergleich` über den
Schlüssel `(datum, titel)` und nicht über Titel allein — die Band spielt ihr
„Dreisam-Brücken-Konzert" fünfmal an fünf Daten, als Titelmenge wäre das ein Eintrag.

**Wörtlich abgeschrieben heißt noch nicht „eine Wiederholung".** Der erste Sammellauf über
die Testfläche lieferte zwei solche Einträge, und beide waren falsch, obwohl beide Passagen so auf
der Seite standen: `'Ab September'` (ein Startzeitpunkt) und `'Nächste Termin am 08.09.26'`
(ein Einzeldatum, das als Termin gehört hätte). Die Belegprüfung kann das nicht sehen — sie
prüft Existenz, nicht Bedeutung.

Deshalb greift zusätzlich `_ist_rhythmus()`: ein Wochentag oder ein Wiederholungswort muss
vorkommen, ein konkretes Datum nicht. Ein bloßer Wochentag genügt, weil „Dienstag, 20:00 –
22:00 Uhr" im Programm des Tibet-Kailash-Hauses genau so dasteht und jeden Dienstag meint.
Dazu nennt der Prompt die Gegenbeispiele ausdrücklich. Nach beiden Änderungen liefert das
Modell bei Kloster St. Lioba gar keinen solchen Eintrag mehr, und die acht echten bei
`tibet-kailash-haus.de` bleiben vollständig erhalten.

**Nach der Umbenennung vollständig nachgemessen**, weil der Auftrag der
neuen Fassung das Feld beim Namen nennt und sich dadurch geändert hat. Sammellauf über alle
acht `test_ok`-Domains: **89 Termine gegen 92 in der Referenz, keine Verschiebung, null
regelmäßige** — die beiden Fehlfunde des ersten Laufs sind weg, `_ist_rhythmus()` und die
Gegenbeispiele im Prompt greifen.

Der einzige auffällige Rückgang war `ensemble-recherche.de` (12 → 8). `--vergleich` auf
identischem Text entlastete den Prompt: dort liefert die neue Fassung **12 Termine gegen 7**
der bewährten. Die Domain schwankt über drei Läufe zwischen 7, 12 und 8 — sie ist der
bekannte Problemfall mit hoher Verwerfungsrate, unabhängig von dieser Änderung.

Der Sammellauf führt einen zweiten Bestand in
`ausgaben/termine_regelmaessig.json`.
`verschmelze_termine_regelmaessig()` dreht die Verfallsregel um: bei Terminen gilt „nicht gefunden heißt
nicht weg", weil ein Datum von selbst verfällt — ein regelmäßiger Termin hat keins und kann
nur dadurch enden, dass sie von der Seite verschwindet. Die regelmäßigen Termine einer Domain werden deshalb
vollständig **ersetzt**. Sicher ist das, weil `scanne()` bei Fehlschlag `None` liefert: ein
misslungener Abruf löscht nichts.

Seit 16.09.2026 **angezeigt**: `baue_webseite.py` liest `termine_regelmaessig.json` und rendert
sie als eigenen Reiter „Regelmäßige Termine" neben „Einzeltermine" (Umschalter über der
Genre-Legende, reines CSS/JS, kein Framework). Sortiert wird nach Wochentag (erkannt am
`rhythmus`-Text, acht feste deutsche Wochentag-Stämme), dann `uhrzeit`, dann `rhythmus`, dann
`titel` — keine Tagesgruppierung, da kein `datum` vorliegt. Der Genre-Filter wirkt in beiden
Reitern gleich. Quellen-Dublettenerkennung über Domains (wie bei `termine.json`) gibt es hier
bewusst nicht: `_selbes_event()` braucht ein `datum` als Anker, das regelmäßigen Terminen fehlt.

### Regionsfilter „Freiburg und Umgebung"

Liegt [`eingaben/region.md`](eingaben/region.md) vor, verwirft `nachpruefen()` jeden Termin,
dessen `ort` **keinen** Namen aus der Liste nennt — Ortsnamen (Freiburg, Kirchzarten,
Emmendingen, Nimburg …) **und** lokale Spielstätten ohne Stadt im Namen (Schopf2, Waldsee,
Ensemblehaus …). Geprüft wird als Teilstring auf der normalisierten Form, damit „Kath.
Pfarrkirche St. Peter" den Eintrag `St. Peter` trifft und „PILSEN (CZ)" keinen. Anders als
bei `kuenstler`/`beschreibung` fällt hier der **ganze** Termin weg: außerhalb der Region ist
er kein Fund, sondern Rauschen. Anlass war `murat-coskun.eu` — ein Freiburger Künstler auf
Tour, dessen Seite Konzerte in Pilsen und Straßburg ankündigte.

Der Modus ist **streng**: ein Termin ganz ohne belegte Ortsangabe fällt ebenfalls raus
(`REGION_LEERER_ORT_OK = False`). **Fehlt `region.md`, ist der Filter komplett aus** — eine
einzeln kopierte `termine_aus_domain.py` verhält sich dann wie zuvor. Neue lokale Spielstätte
= eine Zeile mehr in `region.md`, dieselbe Handarbeit wie beim Eintragen einer Domain.

Ohne Aufzählung erfindet das Modell Kategorien wie „Musiktheater", und die spätere
Auswertung zerfällt. Ein unbekannter Wert wird auf `Sonstiges` gesetzt, nicht verworfen —
ein falsches Etikett macht einen echten Termin nicht ungültig.

---

## Mehrere Seiten, ein Aufruf

Am 26.08.2026 zeigte der zweite Ernstfall, dass eine Startseite oft nicht genügt: die
**Stiftung für Konkrete Kunst** kündigt dort nur Ausstellungen an, ihre sechs Konzerte
stehen unter `/veranstaltungen/`. Das Skript las diese Seite nie — und meldete stattdessen
neun Vernissagen im Wochenabstand, konstruiert aus „Ausstellung 13.09. bis 08.11., geöffnet
sonntags". Alle neun kamen durch, weil nur der Titel geprüft wurde.

Seither werden bis zu vier Unterseiten mitgelesen. Die Auswahl ist rein heuristisch, ohne
zweiten Modellaufruf:

| Regel | wirkt gegen |
|---|---|
| Stichwort im **Linktext** zählt 3, im **Pfad** 1, Schwelle 3 | `Biographische Daten, Ausstellungen` auf `/phleps/` — 3.771 Zeichen Lebenslauf |
| **starke** Wörter (Veranstaltung, Termin, Konzert, Programm, Kalender, Tour) reichen allein, **schwache** (Ausstellung, Vorschau, Lesung) brauchen den Pfad dazu | Themenwörter in beiläufigen Untertiteln |
| Jahreszahl kleiner als das laufende Jahr | die Jahresnavigation `veranstaltungen_1999_2000.html` … `_2025.html` |
| Negativliste (Newsletter, Impressum, Kontakt, Archiv, Tourist/Tourismus …) | `Newsletter abonnieren` beim Vorderhaus — der Linktext nennt „Programm" und „Konzerte" und schlug damit den echten Kalender |
| Stichwort muss ein **Pfad-Wort anführen**, nicht darin stecken | `/event/…-eroeffnungskonzert` schlug `/events` um einen Punkt und schnitt die Übersicht ab |
| bei Punktgleichstand gewinnt der **flachere** Pfad | die Einzelseite vor der Übersicht, die sie verlinkt |
| Host-Vergleich **ohne `www.`** | `kloster-st-lioba.de` liefert ohne www aus und verlinkt mit — alle 136 Links galten als fremde Domain |

Zwei Regeln kamen am 03.09.2026 über `kloster-st-lioba.de` dazu. Die Seite liefert ihre
Startseite **ohne** `www.` aus, verlinkt aber jede Unterseite **mit** — beim zeichengleichen
Hostvergleich galten damit alle 136 Links als fremde Domain, und der Terminkalender wurde nie
gelesen. Übrig blieben die Ankündigungen der Startseite, die keine Uhrzeit nennen.
Derselbe Kalender zeigt **10 von 53** Terminen und hängt den Rest an `?pagerPage_…=2` bis `=6`.
Solchen **Blätter-Links** folgt das Skript seither: gleicher Pfad, andere Abfrage, eine Ziffer
als Linktext — der Parametername ist seitenspezifisch, diese Form nicht. Höchstens
`MAX_BLAETTER` Folgeseiten je gelesener Seite, und die der Startseite zuletzt, weil sie zu
älteren Nachrichten führen statt zu Terminen. Ergebnis bei St. Lioba: **9 Termine vorher,
34–48 nachher**, die Klosterführung erstmals mit ihrer Uhrzeit.

`Tour` kam am 01.09.2026 dazu: `murat-coskun.eu` zeigt auf der Startseite nur die
nächsten vier Termine, die volle Liste (25+) steht unter `/on-tour` — ohne Stichwort nie
gelesen, `WORLD FRAME DRUM DAY` in der Lokhalle fehlte. `Tourist`/`Tourismus` in der
Negativliste fangen den einzigen absehbaren Fehltreffer ab.
| Pfadtiefe über 2 kostet Punkte | Bildseiten wie `/ausstellungen/2026_weihs/weihs_wo_15_2016.html` |
| Dedup über einen **Hash des Textes**, nicht der Adresse | `veranstaltungen/index.html` und `veranstaltungen_2026.html` sind dieselbe Seite |

Die Texte gehen zu **einem** Aufruf zusammen, je Abschnitt eine Zeile `--- <adresse> ---`.
Fünf Aufrufe kosteten fünfmal Systemprompt und Auftrag.

Beim Klavierdepot trifft kein Link ein Stichwort — dort bleibt es bei der einen Seite und
beim alten Ergebnis. Das war die Bedingung.

### Social-Hosts brauchen einen Browser

`instagram.com` lädt die Beitragstexte erst per JavaScript/XHR nach — der `requests`-Pfad
bekäme nur die rund 54 Zeichen des `<title>`. Nicht der Login ist der Knackpunkt, das
JavaScript ist es: ein echter Browser führt es aus, auch ausgeloggt. Für solche Hosts
übernimmt das **optionale** Modul [`tools/social_holen.py`](tools/social_holen.py): es
steuert per CDP einen Chrome, liest Bio + die neuesten vier Beiträge (nach Datum, angepinnte
Alt-Posts fallen raus) und hängt sie im selben `--- <adresse> ---`-Format an denselben
Modellaufruf.

Zwei Betriebsarten, `hole()` wählt selbst:

- **Selbststart (Vorgabe, kein Setup).** Läuft kein Chrome auf dem Debug-Port, startet
  `social_holen.py` selbst einen **headless**-Chrome mit eigenem Profilordner
  (`%LOCALAPPDATA%\kulturfein-chrome-auto`, nicht angemeldet), erledigt die Arbeit und
  beendet ihn wieder — per PID, neben deinem normalen Chrome, ohne Fenster. Reicht für
  **öffentliche** Profile; Instagram kann den ausgeloggten Browser aber zeitweise abblocken
  (429 / Login-Wand), dann bleibt die Domain im Sammellauf fällig.
- **Angedockt (optionales Upgrade).** Startest du [`tools/chrome-debug.cmd`](tools/chrome-debug.cmd)
  (eigener Chrome, Profilordner `%LOCALAPPDATA%\kulturfein-chrome`, Debug-Port 9222) und
  meldest dich dort **einmal** bei Instagram an, nimmt `hole()` diesen — zuverlässiger und
  sieht auch **private** Profile, denen du folgst. Cookie bleibt Wochen bis Monate.

`--kein-browser` erzwingt den `requests`-Pfad. Fehlt `social_holen.py` (Einzeldatei-Kopie),
`pychrome` oder jeder Chrome/Edge, bleibt alles beim Alten bzw. bricht mit klarer Meldung ab.

---

## Die Datumsprüfung

Jedes gemeldete Datum muss im Text stehen, nicht nur der Titel. `datumsfunde()` erkennt vier
Formen und ergänzt ein fehlendes Jahr über den Jahreswechsel — in rund fünfzig Zeilen statt
der mehreren hundert des Vorgängers.

**Zwei Fallen, beide teuer erkauft und beide durch einen Test gesichert:**

Das Klavierdepot schreibt `Freitag 14.August 2026 - 20h` — **ohne Leerzeichen nach dem
Punkt**. Eine Suche nach fertigen Zeichenketten (`"14. August 2026"`) hätte dort alle vier
echten Termine verworfen. Deshalb steht `\s*` um jeden Trenner.

Der Vorderhaus-Kalender schreibt `Oktober 27` als Überschrift und darunter nur noch die
nackten Tage `3`, `9`, `23`. Ohne diese vierte Form hielt der Scanner alle 130 dort
gemeldeten Termine für erfunden — **das Modell hatte recht, die Prüfung war blind.** Ein
Monatskopf färbt seither den Text bis zum nächsten ein. Zwei Einschränkungen mussten dazu:
`14.August 2026` darf kein Kopf sein (sonst wird `- 20h` zum 20. des Monats), und `mai`
darf sein Wortende nicht in `Mainz` finden.

Die Richtung ist bewusst großzügig: **ein Beleg zu viel lässt einen erfundenen Termin durch,
ein Beleg zu wenig wirft einen echten weg.** Gegen die erste Hälfte hilft der Prompt, gegen
die zweite nichts.

---

## `--verbose`

Zwei Blöcke auf stderr — `--json` und Pipes bleiben sauber. Der erste sagt, welche
Unterseiten gelesen wurden und warum die anderen nicht. Der zweite zeigt zu jedem Termin das
Umfeld seines Datums, und das ist der eigentliche Gewinn:

```
2026-09-13  Ausstellung  Duo "But Five" mit Nina Brackrock   (2 Fundstellen)
   ...Foto: Stefan Wiegandt |13.09.2026| bis 08.11.2026 Helga Weihs Between...
   ...W.-M. Vollhardt und M. Glock |13.09.2026| 11:30 Uhr Duo "But Five"...
```

Steht hinter dem Beleg ein `bis`, war es ein Zeitraum; steht dort `11:30 Uhr`, war es ein
Termin. Deshalb werden **alle** Fundstellen gesammelt und nicht nur die erste — sonst zeigt
die Ausgabe für ein Konzert die Ausstellungsdauer und behauptet dem Leser gegenüber das
Falsche.

---

## Sammel-Lauf über viele Domains

`termine_aus_domain foo.de` bleibt der Einzelaufruf. Für den regelmäßigen Durchgang über eine
Domainliste kommt [`tools/domain_lauf.py`](tools/domain_lauf.py) dazu — es weiß nichts vom
Modell, sondern führt Buch: **wann** war welche Domain dran, und was gilt über mehrere Läufe
hinweg als derselbe Termin.

```
domain_lauf                 # alles Fällige, Vorgabe 7 Tage
domain_lauf --frische 0     # alles neu scannen
domain_lauf --nur foo.de    # eine Domain, ohne domains.md zu ändern
domain_lauf --liste x.md    # andere Domain-Liste statt domains.md
domain_lauf --trocken       # zeigen, was fällig wäre, nichts tun
```

Zum Debuggen liegt in [`eingaben/test-domains.md`](eingaben/test-domains.md) ein kleiner
Satz von fünf Domains, die je einen anderen Code-Pfad ausreizen (Mehrseiten-Crawl,
Weiterleitung, Instagram/Browser, Veranstaltungsort ohne Ausbeute, nicht-deterministische
Quelle). `domain_lauf --liste eingaben/test-domains.md --frische 0` läuft in unter einer
Minute statt über die ganze Stammliste. Schreibt in dieselbe `termine.json` /
`domain_log.json` — die fünf sind auch in `domains.md` aktiv, das Verschmelzen bleibt
sauber pro Domain.

Drei Dateien, drei getrennte Aufgaben:

| Datei | Rolle |
|---|---|
| `eingaben/domains.md` | Eingabe, von Hand gepflegt. Eine Domain je Zeile, `#` für Kommentare |
| `ausgaben/domain_log.json` | Buchhaltung: welche Seiten gelesen, wann zuletzt. Je Scan überschrieben |
| `ausgaben/termine.json` | Die Funde aller Domains zusammen — **kein** Archiv |

`domain_log.json` führt **kein** `quelle`-Feld: das wäre nur eine Dopplung von `seiten[0]`,
das per Konstruktion immer die Startadresse nach Weiterleitung ist — und der Name kollidiert
mit der Domain selbst, die man ebenso „Quelle" nennen würde.

### Was derselbe Termin ist

Die Frage entscheidet alles beim zweiten Lauf. Der **Titel taugt nicht als Schlüssel** — er
schwankt zwischen Läufen (Punkt 3 unter „Was noch fehlt"). Wer ihn in den Schlüssel nimmt,
bekommt bei jedem Rescan Dubletten statt Aktualisierungen.

Deshalb müssen `domain` + `datum` + `uhrzeit` exakt stimmen — die Felder, die
`nachpruefen()` ohnehin gegen den Seitentext belegt hat — und der Titel muss nur **ähnlich**
sein: erst Teilstring-Test (fängt `IMPERIA` gegen `IMPERIA ... ein drolldreistes
Soloschauspiel`), dann `difflib.SequenceMatcher` ab 0.6. Bewusst **ohne** Modellaufruf: ob
zwei Zeichenketten dasselbe meinen, ist Mechanik, und eine nicht-deterministische
Dublettenprüfung wäre hier das Letzte, was man will. Konservativ eingestellt — lieber eine
sichtbare Dublette als zwei echte Termine fälschlich verschmolzen.

Das deckt nur die **Rescan-Dublette je Domain** — `verschmelze()` trennt `fremd`/`eigen` und
rührt fremde Domains nie an. Die **Quellen-Dublette über Domains** (dasselbe Konzert auf
`barockorchester.de`, `ensemble-recherche.de` und `mehrklang-freiburg.de`) bleibt in
`termine.json` stehen — dort ist jede Meldung ein eigener, verifizierter Fund — und wird
erst beim Rendern zusammengefasst (siehe „Die Webseite").

### Zwei Regeln zum Bestand

**Vergangenes fliegt raus**, auch aus `termine.json` selbst. Maßgeblich ist das *heutige*
Datum beim Aufräumen, nicht das des Laufs, der den Eintrag schrieb — sonst bliebe ein Termin
ewig stehen, der beim Schreiben noch in der Zukunft lag.

**Nicht gefunden heißt nicht weg.** Ein alter Termin, der beim Rescan fehlt, aber noch nicht
vergangen ist, bleibt stehen. Ein Lauf kann eine Unterseite verfehlen (Zeichenbudget,
Timeout, Umbau der Website); das darf keine bereits belegten Termine löschen. Ein
fehlgeschlagener Scan aktualisiert auch das Besuchsdatum nicht — die Domain bleibt fällig.

### Die Webseite

[`tools/baue_webseite.py`](tools/baue_webseite.py) rendert `termine.json` zu `index.html` — reines
Templating, kein Modellaufruf, keine Kosten. Eigener Befehl, kein Schalter an
`domain_lauf.py`, dieselbe Trennung wie zwischen Einzelaufruf und Sammel-Lauf:

```
baue_webseite
```

Template und CSS sind aus dem Nachbarprojekt `schwarzes_brett_webseite_test` **kopiert und
angepasst** (Zeitungs-/Amtsblatt-Stil, kein JavaScript, komplett serverseitig gerendert,
Light/Dark automatisch über `prefers-color-scheme`) — bewusst kopiert statt referenziert,
damit dieses Projekt nicht von einem Pfad in einem fremden Ordner abhängt. Deren
Datenschema passte nicht direkt: `place`/`title`/`description` wurden zu `ort`/`titel`/
`beschreibung`, die zweistufige Kategorisierung (`tag`+`topic`, 5 Werte) wurde auf das
einstufige `genre` (9 Werte, siehe oben) reduziert, `kuenstler` kam neu dazu.

`termine.json` ist von `domain_lauf.py` schon aufgeräumt — Vergangenes entfernt, Rescan-
Dubletten je Domain verschmolzen (siehe oben) —, deshalb braucht `baue_webseite.py` keinen
Zeitfenster-Filter. **Eine Dublettenstufe bleibt aber ihm:** `_gruppiere()` fasst vor dem
Rendern die **Quellen-Dubletten über Domains** zusammen — gleiches `datum` + `uhrzeit`,
Titel über die Menge der Kernworte ähnlich (nicht die Reihenfolge — „Ensemble-Akademie
Eröffnungskonzert" ↔ „Eröffnungskonzert der Ensemble-Akademie Freiburg") **und** der Ort
passt. Pro Cluster wird nur der **vollständigste** Datensatz gezeigt, die übrigen entfallen
für den Bau; `termine.json` bleibt unangetastet. Titel **und** Ort müssen zusammenpassen,
sonst kollabierte „Troja …" (Schopf2) mit „ZUR NACHT im Freiburger Münster" — gleiches
`datum` + `uhrzeit`. Der Link je Termin ist die `fundstelle` des Termins (die konkrete
Unterseite), mit Fallback auf `domain_log.json → seiten[0]`, wenn sie fehlt. Als sichtbare
Beschriftung dient die Domain (`mehrklang-freiburg.de ↗`), die volle URL steht im
`title`-Tooltip.

Abhängigkeiten: `requests`, `beautifulsoup4`, `lxml`; `jinja2` für `baue_webseite.py`;
`pychrome` **optional**, nur für Social-Hosts (siehe „Social-Hosts brauchen einen Browser").

---

## Stand

**Belegt sind drei Fälle**, gemessen am 26.08.2026:

| | Seiten | Termine | verworfen | Kosten |
|---|---:|---:|---:|---:|
| Klavierdepot Freiburg | 1 | 4 | 0 | 0,0066 $ |
| Stiftung für Konkrete Kunst | 3 | 6 | 0 | 0,017 / 0,007 $ |
| Vorderhaus (Kalenderseite) | 4 | 130 | 0 | 0,0488 $ |

**Barockkirche St. Peter kam am 30.08.2026 dazu** und brachte drei Fehler ans Licht, die
alle in der *Nachprüfung* lagen, nicht im Modell — 8 von 14 gemeldeten Terminen wurden
verworfen, mindestens 7 davon zu Unrecht:

| Fehler | Ursache | nach dem Fix |
|---|---|---|
| `_mit_jahr()` | wählte bei jahresloser Angabe *ein* Jahr; `23.08.` wurde zu `2027-08-23`, galt damit als unbelegt | gibt beide Kandidaten zurück — Belegprüfung ist Existenz-, keine Interpretationsfrage |
| `_ist_archiv()` | prüfte `max(jahre)` über den ganzen Pfad; bei `/orgelkonzerte-2026/orgelkonzerte-2019/` gewann 2026 | prüft je Pfadsegment; `spielzeit-2025-2026` bleibt trotzdem kein Archiv |
| `_normal()` | verglich Titel roh; die Seite mischt vier Anführungszeichen-Sorten | Zeichentabelle für typografische Varianten |

Ergebnis: **12 übernommen statt 6**, 47 statt 9 Archivseiten korrekt aussortiert (dadurch
kamen die echten 2026er-Programmseiten ins Zeichenbudget statt einer Archivseite von 2019).
Der Fehler wanderte mit dem Kalender: am 26.08. kam der 30.08. noch durch, ab dem 31.08.
wäre auch er gefallen.

Die zwei Werte bei der Stiftung sind derselbe Aufruf zweimal: 1,7 ct beim ersten Lauf,
0,7 ct beim zweiten. Den Unterschied macht der Prompt-Cache. Für eine Hochrechnung auf viele
Orte zählt die **erste** Zahl — jede Domain ist beim ersten Mal kalt.

Beim Klavierdepot ist das Ergebnis unverändert gegenüber der Einseiten-Fassung. Bei der
Stiftung sind die neun Geistertermine weg und die sechs echten Konzerte da, darunter das
gesuchte `2026-11-08 11:30 Nurit Stark, Violine`. Das Skript läuft weiterhin eigenständig —
in einen leeren Ordner kopiert und dort gestartet, funktioniert es; es braucht nur
`requests` und `beautifulsoup4`.

**Ein Gegenversuch ist geparkt.** [`tools/archiv/termine_aus_domain_via_claude_webfetch.py`](tools/archiv/termine_aus_domain_via_claude_webfetch.py)
lässt das Modell mit `--tools WebFetch` selbst navigieren, ohne lokale Heuristik. Getestet
am 30.08.2026, gleicher Fall Klavierdepot: 1 Termin statt 4, 0,0753 $ statt 0,0062 $ — das
Modell hat plausible, aber nicht existierende Unterseiten (`/programm`, `/veranstaltungen`,
`/termine`) geraten, statt nur echten Links zu folgen. Details und Docstring der Datei.

## Was noch fehlt

**1. Große Seiten kosten spürbar mehr.** Der Vorderhaus-Lauf liegt bei 4,9 ct — das
Zwanzigfache des Klavierdepots, überwiegend Ausgabe-Token für 130 Termine. Eine einzelne
Unterseite kann außerdem das gesamte Zeichenbudget aufbrauchen: beim E-Werk Freiburg hat
`aktuelles-programm` mit 26.000 Zeichen die drei folgenden Kandidaten verdrängt.
`--verbose` meldet das ehrlich („Zeichenbudget erschöpft"), gelöst ist es nicht.

Die **Ausgabe**seite hat eine zweite, härtere Grenze, gemessen am 07.09.2026: Haiku
liefert höchstens **32.000 Ausgabe-Token** (`modelUsage.maxOutputTokens` in der
CLI-Antwort). Wird sie überschritten, kommt keine gekappte Antwort, sondern ein Abbruch —
`exit 1`, und im Feld `result` steht „Claude's response exceeded the … output token
maximum". Der Vorderhaus-Lauf braucht rund 15.000, liegt also bei knapp der Hälfte.

Zwei Dinge waren daran zu reparieren, keins davon war das befürchtete stille Verschlucken:
die Ursache stand in **stdout**, angezeigt wurde aber `stderr` — man sah „endete mit 1"
und sonst nichts (`_fehlergrund()`). Und ab 75 % der Grenze warnt der Lauf jetzt, solange
er noch durchgeht. Ungelöst bleibt, was bei einem Veranstalter mit mehr als etwa 250
Terminen zu tun ist; die naheliegende Antwort wäre, den Text an den
`--- <adresse> ---`-Grenzen zu teilen und zwei Aufrufe zu machen.

**2. Die Prüfung ist auf Kalenderseiten wirkungslos.** Wo ein Monatsgitter alle Zahlen von
1 bis 31 aufführt, ist jedes Datum belegbar. Der Schutz greift dort, wo die Stiftung
scheiterte — bei Fließtext mit wenigen Datumsangaben —, und nicht dort, wo ohnehin ein
Kalender steht.

**3. Der Titel schwankt zwischen Läufen.** Mal steht `"IMPERIA"` in der Ausgabe, mal
`"IMPERIA ... ein drolldreistes Soloschauspiel"`. Beides ist wortgetreu, aber unterschiedlich
weit gefasst. Für einen Abgleich zwischen zwei Läufen ist das eine Fehlerquelle.

**4. Das Genre trägt bei Kleinkunst nicht.** Beim Vorderhaus landete die Mehrzahl der 130
Termine auf `Sonstiges` — Kabarett und Comedy haben in der geschlossenen Liste keinen Platz.
Entweder die Liste wächst, oder das Feld sagt für diese Häuser nichts aus.

**5. Vergangenes wird mitgemeldet.** Die Jahresliste der Stiftung enthält auch März bis
Juli; die lesbare Ausgabe markiert sie als `(vorbei)`, gefiltert wird nicht.

**6. Eine Domain je Lauf.** Kein Stapelbetrieb, keine Ortsliste. Bei 0,7 bis 5 ct je Aufruf
wären 291 Orte grob 2 bis 15 $ — die Frage ist nicht der Preis, sondern woher die Liste
kommt.

**7. Kein Tag- und Umkreisfilter.** Das Genre-Feld ist da, die Abfrage darauf noch nicht.

**8. Kein JavaScript — außer für Social-Hosts.** `jazzhaus.de` liefert 791 Zeichen
Startseite und 510 Zeichen Programmseite — der Inhalt wird nachgeladen. Der Vorgänger hatte
dafür Playwright. Für `instagram.com` gibt es jetzt den Browser-Weg über
[`tools/social_holen.py`](tools/social_holen.py) (siehe „Social-Hosts brauchen einen
Browser"); für normale JS-Seiten wie `jazzhaus.de` ist das nicht gelöst.

---

## Was bewusst nicht übernommen wurde

- **Die Heuristik-Kaskade** aus `scan_events.py`. Sie ist billiger als jeder Modellaufruf
  und war für strukturierte Kalenderseiten richtig — aber sie ist auch der Grund, warum das
  Vorgängerprojekt neunzehn gelbe Orte hatte, an denen sie scheiterte. Ob sie zurückkommt,
  entscheidet sich, wenn Punkt 1 gemessen ist.
- **`--bare`.** Das Flag würde auch die letzten 1.300 Token der globalen `CLAUDE.md`
  entfernen und den Nebenaufruf abschalten, den Claude Code für Attribution und Auto-Memory
  selbst startet. Es liest aber laut Hilfe „strictly ANTHROPIC_API_KEY, OAuth and keychain
  are never read" — ohne API-Schlüssel endet der Aufruf mit `terminal_reason: "api_error"`.
  Der Weg hier läuft über die vorhandene Claude-Code-Anmeldung, ohne separate Rechnung.
