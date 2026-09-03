# Hosting: wo läuft was?

Notiz vom 2026-09-02. Frage war: Projekt auf GitHub schieben, Live-Seite
irgendwo hosten — was gehört wohin?

## Die eine Tatsache, die alles entscheidet

Der Scanner braucht **die `claude`-CLI mit einem angemeldeten Konto**.
Das ist kein pip-Paket, das man auf einen Webspace kopiert — es ist eine
authentifizierte Anwendung, an der Kosten hängen. Dazu kommen für
Instagram ein echter Chrome (`social_holen.py` über das DevTools-Protokoll)
und rund 30.000 Zeichen Seitentext je Domain.

**Konsequenz:** Der Scan läuft auf der eigenen Maschine. Veröffentlicht wird
nur das Ergebnis — eine einzige statische Datei, `index.html`.

Damit zerfällt die Frage „welcher Hoster gibt mir einen Cron-Job?": Der
Hoster liefert nur eine statische Datei aus, er rechnet nichts. Der
Zeitplan gehört auf die Maschine, die scannt — unter Windows die
**Aufgabenplanung**, nicht der Hoster.

## Die Aufteilung

```
LOKAL (Laptop)                          ÖFFENTLICH
──────────────                          ──────────
domain_lauf.py    → claude -p
                  → termine.json
baue_webseite.py  → index.html   ──────▶  ausgeliefert
                                          (statisch, kein Server nötig)
```

## Publikationswege im Vergleich

| | GitHub Pages | Ionos-Webspace | Claude-Artefakt |
|---|---|---|---|
| Kosten | 0 € | schon bezahlt | 0 € |
| Repo muss öffentlich sein | **ja** (kostenloses Konto) | nein | nein |
| Eigene Domain | möglich | ja, vorhanden | nein |
| Veröffentlichen = | `git push` | FTP/SFTP-Upload, zu skripten | Artefakt neu publizieren |
| Zusatzinfrastruktur | keine | Upload-Skript | keine |
| Taugt als Aushängeschild | ja (Repo + Seite) | nur die Seite | nein, geteilter Link |

**GitHub Pages** ist der kürzeste Weg: `index.html` liegt ohnehin im Repo,
ein `git push` ist gleichzeitig das Deployment, und die Seitenhistorie fällt
gratis mit ab. Preis: das Repository muss öffentlich sein.

**Ionos** ist die Wahl, wenn das Repo privat bleiben soll oder die eigene
Domain zählt. Dann braucht es ein Upload-Skript (lftp/curl/WinSCP), das nach
`baue_webseite.py` läuft — ein Dreizeiler, aber ein zusätzliches Teil.

**Claude-Artefakt** ist keine Alternative für die Live-Seite (fremde Domain,
kein dauerhafter Auftritt), aber gut, um jemandem schnell einen Stand zu
zeigen.

## Ablauf, wenn GitHub Pages

1. einmalig: Repo anlegen, Pages auf Branch `main` / Ordner `/` stellen
2. je Durchgang, lokal:
   ```
   domain_lauf                    # scannt, was fällig ist
   baue_webseite                  # index.html neu
   git add index.html ausgaben/   # oder nur index.html
   git commit -m "Termine <datum>"
   git push
   ```
3. optional automatisieren: Windows-Aufgabenplanung ruft ein Skript, das
   diese Schritte hintereinander ausführt

Ein unbeaufsichtigter Lauf ist mit Vorsicht zu genießen: Er kostet Geld je
Lauf und die Trefferqualität schwankt (siehe README). Erst beobachtet
laufen lassen, dann automatisieren.

## Zu den Motiven

- **Backup** — trägt nur halb. Das Projekt liegt bereits in Dropbox, also
  schon außerhalb der Maschine. GitHub bringt echte Versionshistorie statt
  Dateiversionen; das ist der eigentliche Gewinn, nicht das Backup.
- **Sichtbarkeit / Akquise** — ein dokumentiertes Repo plus laufende Seite
  ist für technisch interessierte Gesprächspartner ein brauchbares
  Arbeitsbeispiel. Aber: es legt auch die Arbeitsweise offen, und es ist
  ein Projekt, in das man beliebig viel Politur stecken kann, ohne dass ein
  Lead näher rückt. Gut genug ist gut genug.
- **Erste öffentliche Hosting-Erfahrung** — dafür ist GitHub Pages der
  geradlinigste Einstieg: kein Server, kein FTP, kein Zertifikat.

## Offen

- öffentlich oder privat? (Pages auf kostenlosem Konto ⇒ öffentlich)
- `README.md` mit hochladen? 564 Zeilen mit Messwerten, Kosten, Interna
- `ausgaben/*.json` versioniert lassen oder aus der Versionierung nehmen?
  Sie rauschen bei jedem Lauf und blähen die Historie
