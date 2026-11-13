# Regeln für dieses Repo

- Öffentliches Repo: keine Personen-, Firmen- oder Kundennamen, keine Secrets. Vor jedem Push prüfen.
- Neue App, neues Bookmarklet, neue Vorlage mit Skill-Bezug, neuer Workflow oder neues Skript: im Werkzeug-Verzeichnis der Wissensbasis eintragen (Artefakt-Datenbank, slug `c93ec594-0a21-4c65-9a8a-4694f7fca0c5`, Dokument `wiki/werkzeuge`: Name, Zweck, Ort/URL, Karte IDEE-xxx, Artikel, Stand) und die passende Karte nachführen. Ohne Zugriff auf die Datenbank: am Ende der Sitzung darauf hinweisen.
- Vorlagen in `prompts/library.json` sind die neutrale Kurzform eines Claude-Skills; Feld `skill` pflegen.
- Nach Änderungen an App-Dateien `CACHE` in `sw.js` hochzählen und `CHANGELOG` in `app.js` ergänzen.
- Schweizer Hochdeutsch ohne ß, Daten TT.MM.JJJJ.
