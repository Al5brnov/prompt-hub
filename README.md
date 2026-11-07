# Prompt Hub

Kleine Web-App für Android, die markierten Text mit einer Prompt-Vorlage an einen KI-Assistenten übergibt.
Sie erscheint nach der Installation im Teilen-Menü von Android.

## Installation (Android, Chrome)

1. Die Seite dieser App in Chrome öffnen.
2. Menü (⋮) → **Zum Startbildschirm hinzufügen** bzw. **App installieren**.
3. Fertig. «Prompt Hub» erscheint jetzt im Teilen-Menü.

## Nutzung

1. In einer beliebigen App Text markieren → **Teilen** → **Prompt Hub**.
2. Vorlage in der Auswahlliste wählen (Favoriten zuoberst), allfällige Felder ausfüllen, optional eine Richtung eingeben.
3. **Senden**: Der Prompt wird an das gewählte Ziel übergeben und zusätzlich in die Zwischenablage kopiert.

Ohne Teilen: App öffnen, **Einfügen** tippen.

## Aufbau

| Register | Inhalt |
|---|---|
| Prompt | Vorlage wählen, Inhalt, Senden |
| simap | Radar mit neuen Ausschreibungen und Zuschlägen, Filter, Sortierung, Auswahl bewerten |
| Bibliothek | Alle Vorlagen nach Kategorie, Suche, Favoriten, eigene Vorlagen anlegen, Export/Import |
| Mehr | Eigener Kontext, Zeitjournal, Weiterentwicklung, Datensicherung, Änderungen |

## Ziele

| Ziel | Übergabe |
|---|---|
| Claude | Link mit `?q=` (nicht offiziell dokumentiert), Fallback Einfügen |
| Andere App | Android-Teilen-Menü, z.B. an eine installierte KI-App |
| Gemini | Zwischenablage, im neuen Fenster einfügen |
| ChatGPT | Link mit `?q=` |
| Perplexity | Link mit `?q=` |

Sehr lange Prompts (über ca. 8'000 Zeichen) werden nur kopiert.

## Datenschutz

- Alles läuft im Browser auf dem Gerät. Es gibt keinen Server, kein Tracking und keine Cookies.
- Gespeichert werden lokal nur Einstellungen, Favoriten, eigene Vorlagen und der optionale eigene Kontext.
- Text verlässt das Gerät nur, wenn Sie ihn aktiv an einen KI-Dienst senden. Dort gelten dessen Bedingungen.

## Ausschreibungen (simap.ch)

Die Vorlage «Ausschreibung Go/No-Go» bewertet eine öffentliche Ausschreibung.
Wird ein Link auf ein simap-Projekt geteilt, versucht die App, Projektkopf und Publikationsdetails über die öffentliche simap-API zu laden.
Lässt simap den Abruf aus der App nicht zu, die Seite in Chrome öffnen, den Text markieren und teilen.
Ausschreibungsunterlagen (PDF) erfordern ein Login und werden nicht geladen.

**simap-Radar:** Die GitHub Action `.github/workflows/simap-radar.yml` sucht werktags am Morgen
nach neuen Publikationen (Ausschreibung, Präqualifikation, Vorankündigung) zu den Stichworten in
`radar/config.json` und schreibt die Treffer mit Details nach `radar/latest.json`.
Die simap-Volltextsuche liefert viel Ausschuss (z.B. «SAP» in «sapeurs-pompiers»). Das Skript filtert deshalb in drei Stufen:
1. **Wortgrenzen:** Akronyme wie SAP, ERP, CRM, AMS zählen nur exakt und in Grossbuchstaben.
2. **CPV-Code:** Publikationen nur mit Bau-, Fahrzeug-, Reinigungs- oder ähnlichen CPV-Codes (`excludeCpvPrefixes`) fallen weg. Begriffe unter `context` zählen nur, wenn ein IT- oder Beratungs-CPV (`itCpvPrefixes`) vorliegt.
3. **Umfang:** Dienstleistungen rund um Software, Beratung, Betrieb und Support. Hart ausgeschlossen: Bauaufträge, Haupt-CPV ausserhalb von IT-Diensten (72), Software (48), Unternehmensberatung (794) und IT-Schulung (80533) sowie Hardware und Server (`mainCpvExclude`). IT-Betrieb, Infrastruktur und Service Desk (`softCpvExclude`, `softExcludeWords`) bleiben drin, sobald ein Kernbegriff wie SAP oder ERP vorkommt. Die Trefferliste `history.csv` zeigt das Ergebnis in den Spalten «Haupt-CPV», «Auftragsart» und «Umfang» (passt / ausserhalb: Grund), auch für ältere Zeilen.
4. **Relevanz-Score:** Kernbegriff im Titel 5, in der Beschreibung 3, Kontextbegriffe bis 4, IT-CPV 2, Ausschreibung/Präqualifikation 1. Unter `minScore` fällt ein Treffer weg, höchstens `maxItems` Treffer.

Feinsteuerung in `radar/config.json`: `core` (treffen allein), `context` (nur mit IT-CPV), `excludeWords` (im Titel), `minScore`, `maxItems`.

Im Register «simap» zeigt das Symbol die Zahl neuer Treffer. Auswählen und «Ausgewählte bewerten»
füllt den Inhalt und wählt die Vorlage «Ausschreibungen Triage». Manuell starten: Actions → simap-Radar → Run workflow.

**Marktinfo Zuschläge:** Jeder Suchlauf erfasst die Zuschläge mit IT- oder Beratungs-CPV
(`marketAllItAwards` in `radar/config.json`) und schreibt pro Zuschlagsempfänger eine Zeile nach
`radar/awards.csv` (Excel) und `radar/awards.json` (App). Die Liste wächst fortlaufend.
Im Register «simap» unter «Zuschläge» zeigt die App ein Anbieter-Ranking mit Zuschlagssummen.
«Marktanalyse erstellen» füllt die Vorlage «Zuschläge: Marktanalyse». Die eigene Firma lässt sich unter «Mehr»
nur auf dem Gerät hinterlegen und wird dann hervorgehoben.
Bei «Ausgewählte bewerten» hängt die App frühere Zuschläge desselben Auftraggebers an den Inhalt an.

**Zuschlags-Historie:** Actions → «simap-Zuschlags-Historie» → Run workflow holt die Zuschläge der letzten 1–4 Jahre mit derselben Logik (je Jahr ein Job, bis ca. 5,5 Std.) und ergänzt `radar/awards.csv`. Stundensätze werden übernommen, wo sie im Publikationstext stehen (Spalten «Stundensatz CHF» und «Stundensatz Fundstelle»). Preisblätter in den Ausschreibungsunterlagen sind ohne Login nicht zugänglich.

**Import in Excel (Power Query):** Daten → Daten abrufen → Leere Abfrage → Erweiterter Editor:

```
let
  Quelle = Csv.Document(Web.Contents("https://raw.githubusercontent.com/Al5brnov/prompt-hub/main/radar/awards.csv"),
           [Delimiter=";", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
  Kopf = Table.PromoteHeaders(Quelle, [PromoteAllScalars=true]),
  Typen = Table.TransformColumnTypes(Kopf, {{"Zuschlagsdatum", type date}, {"Preis CHF", type number},
          {"Angebote", Int64.Type}, {"Anzahl Zuschläge", Int64.Type}, {"erfasst", type date}}, "en-US")
in
  Typen
```

Für die Ausschreibungen dieselbe Abfrage mit `radar/history.csv`, ohne den Schritt «Typen» (Ergebnis = `Kopf`). Abfrageeigenschaften: «Daten beim Öffnen der Datei aktualisieren».

## Vorlagen und Claude-Skills

Einzelne Vorlagen nennen im Feld `skill` einen passenden Claude-Skill (z.B. `ausschreibung-go-no-go`, `hermes-konzept`, `sap-sd-mm-experte`, `firmenvorlagen`).
Ist das Ziel Claude, hängt die App den Hinweis an, den Skill zu nutzen, falls er verfügbar ist (ausser der Prompt nennt ihn schon). Bei anderen Zielen bleibt der Prompt unverändert.
Die Vorlage ist die öffentliche, neutrale Kurzform. Der Skill enthält das ausführliche Vorgehen und eigenes Fachwissen und bleibt privat.
Verbesserungen fliessen in beide Richtungen: Bewährt sich etwas im Skill, wird die Vorlage in neutraler Form nachgeführt, und umgekehrt.
Inhalte in diesem Repo bleiben ohne Personen- und Firmennamen.

## Zeitjournal

Zweite App im Unterordner [`zeitjournal/`](zeitjournal/): Arbeitszeit per Tipp auf Favoriten erfassen
und wöchentlich als Matrix (PSP-Element × Tag, auf 0.25 h gerundet) für die Zeiterfassung exportieren.
Installation wie oben, Daten bleiben auf dem Gerät. Backup als Datei unter «Favoriten».

## Anpassen

Gemeinsame Vorlagen stehen in `prompts/library.json` (Kategorien und Prompts, Platzhalter als `{{Feldname}}`).
Eigene Vorlagen legt man in der App unter «Bibliothek» an. Sie bleiben auf dem Gerät und lassen sich als Datei exportieren.
Die App-Logik steht in `app.js`, die Ziele in `TG`.
Nach Änderungen in `sw.js` die Konstante `CACHE` hochzählen, damit installierte Apps das Update laden.
