# Meta-Wizard

**Meta-Wizard …** (Strg+T) bearbeitet die Tags von Musikdateien (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV), ähnlich wie MP3TAG.

## Grundlagen
- Die Titelliste zeigt die Dateien des aktuellen Ordners mit ihren Tags. Spalten wählt man per Rechtsklick auf die Spaltenköpfe, dort lassen sich auch eigene Felder anlegen.
- In der Seitenleiste bearbeitet man die markierten Titel. Bei mehreren Titeln mit unterschiedlichen Werten steht dort `< beibehalten >`: Was man nicht anfasst, bleibt in jeder Datei, wie es ist.
- Änderungen sind zuerst nur **vorgemerkt** und grün markiert. Erst **Tag speichern** schreibt sie in die Dateien. **Rückgängig** macht das letzte Speichern rückgängig.
- **Cover**: Bild hineinziehen oder Rechtsklick auf das Cover zum Laden, Speichern oder Entfernen.

## Konverter
- **Dateiname → Tag**, **Tag → Dateiname**, **Tag → Tag**: mit Formatstrings wie `%track% - %title%`. Es gibt eine Vorschau und Vorlagen.
- **Tag → Textdatei/CSV** und **Textdatei → Tag**: zum Bearbeiten in LibreOffice oder zum Übernehmen einer Titelliste aus dem Internet. Das Zuordnungsfenster mit Platzhaltern gleicht fehlende Zeilen aus.
- **Nummerieren …**: Tracknummern von oben nach unten, wahlweise mit Gesamtzahl (z. B. „01/12“).
- **Playlist erstellen …**: M3U8-Playlist mit relativen oder absoluten Pfaden.
- **ReplayGain …**: misst die Lautheit mit ffmpeg (EBU R128) und trägt Titel- und Albumwerte ein. Die Ziel-Lautheit steht in den [Einstellungen](settings.md). Dafür muss ffmpeg installiert sein.

Der Meta-Wizard schließt sich über den Knopf „Schließen“ oder wenn man ihn erneut aufruft. Vorgemerkte Änderungen gehen dabei nur nach Rückfrage verloren.
