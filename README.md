# Prompt Hub

Kleine Web-App für Android, die markierten Text mit einer Prompt-Vorlage an einen KI-Assistenten übergibt.
Sie erscheint nach der Installation im Teilen-Menü von Android.

## Installation (Android, Chrome)

1. Die Seite dieser App in Chrome öffnen.
2. Menü (⋮) → **Zum Startbildschirm hinzufügen** bzw. **App installieren**.
3. Fertig. «Prompt Hub» erscheint jetzt im Teilen-Menü.

## Nutzung

1. In einer beliebigen App Text markieren → **Teilen** → **Prompt Hub**.
2. Aufgabe wählen, optional eine Richtung eingeben.
3. **Senden**: Der Prompt wird an das gewählte Ziel übergeben und zusätzlich in die Zwischenablage kopiert.

Ohne Teilen: App öffnen, **Einfügen** tippen.

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
- Gespeichert werden lokal nur die letzte Aufgabe, das letzte Ziel, die Anrede und der optionale eigene Kontext.
- Text verlässt das Gerät nur, wenn Sie ihn aktiv an einen KI-Dienst senden. Dort gelten dessen Bedingungen.

## Ausschreibungen (simap.ch)

Die Vorlage «Ausschreibung Go/No-Go» bewertet eine öffentliche Ausschreibung.
Wird ein Link auf ein simap-Projekt geteilt, versucht die App, Projektkopf und Publikationsdetails über die öffentliche simap-API zu laden.
Lässt simap den Abruf aus der App nicht zu, die Seite in Chrome öffnen, den Text markieren und teilen.
Ausschreibungsunterlagen (PDF) erfordern ein Login und werden nicht geladen.

## Zeitjournal

Zweite App im Unterordner [`zeitjournal/`](zeitjournal/): Arbeitszeit per Tipp auf Favoriten erfassen
und wöchentlich als Matrix (PSP-Element × Tag, auf 0.25 h gerundet) für die Zeiterfassung exportieren.
Installation wie oben, Daten bleiben auf dem Gerät. Backup als Datei unter «Favoriten».

## Anpassen

Die Vorlagen stehen in `index.html` in der Liste `T`, die Ziele in `TG`.
Nach Änderungen in `sw.js` die Konstante `CACHE` hochzählen, damit installierte Apps das Update laden.
