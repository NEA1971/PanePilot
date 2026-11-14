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
- **Disc-Nummern …**: vergibt Disc-Nummern für mehrteilige Alben – nach Unterordner (z. B. CD1, CD2), neu, sobald die Tracknummer wieder von vorn beginnt, oder von Hand. Die Anzahl der Discs kann man im Disc-Feld als „1/2“ oder in einem eigenen Feld DISCTOTAL eintragen.
- **MusicBrainz …**: sucht das Album in der freien Musikdatenbank [MusicBrainz](https://musicbrainz.org) (dafür ist eine Internetverbindung nötig).
  1. Album und Interpret sind aus den Tags vorbelegt und lassen sich ändern.
  2. Die Trefferliste lässt sich nach jeder Spalte sortieren. Grün markiert sind Veröffentlichungen mit so vielen Tracks, wie Dateien ausgewählt sind.
  3. Im Übernahme-Fenster stehen oben die Titel- und Album-Felder mit Häkchen – nur angehakte Felder werden übernommen, Werte lassen sich per Doppelklick ändern – und das Cover (aus dem Cover Art Archive, höchstens 1200 × 1200 Pixel). Unten ordnet man die MusicBrainz-Titel den Dateien zu, wie bei „Textdatei → Tag“. Gelb heißt: Die Länge weicht um mehr als 5 Sekunden ab.
  4. **OK** merkt die Werte grün vor, **Tag speichern** schreibt sie. Als Jahr wird das Jahr der Erstveröffentlichung eingetragen. Die MusicBrainz-Kennungen werden so gespeichert wie von MusicBrainz Picard.
- **Playlist erstellen …**: M3U8-Playlist mit relativen oder absoluten Pfaden.
- **ReplayGain …**: misst die Lautheit mit ffmpeg (EBU R128) und trägt Titel- und Albumwerte ein. Die Ziel-Lautheit steht in den [Einstellungen](settings.md). Dafür muss ffmpeg installiert sein.

Der Meta-Wizard schließt sich über den Knopf „Schließen“ oder wenn man ihn erneut aufruft. Vorgemerkte Änderungen gehen dabei nur nach Rückfrage verloren.
