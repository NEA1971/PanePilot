# Meta-Wizard

**Meta-Wizard …** (Strg+T) bearbeitet die Tags von Musikdateien (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV), ähnlich wie MP3TAG, und die Metadaten von Fotos (siehe unten).

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

## Fotos
Enthält der Ordner Fotos, zeigt der Meta-Wizard deren Metadaten (EXIF, IPTC, XMP). Sind Musik und Fotos gemischt, wählt man oben mit **„Musik | Fotos“** aus, was angezeigt wird; vorgewählt ist die Art mit den meisten Dateien.
- **Lesen und schreiben**: JPEG, PNG, TIFF, WebP. **HEIC/HEIF** (Handyfotos) nur, wenn das Programm **exiftool** installiert ist (`sudo apt install libimage-exiftool-perl`), sonst nur lesen. **RAW**-Dateien (CR2, NEF, ARW, DNG …) werden nur gelesen.
- **Bearbeiten**: Titel, Beschreibung, Schlagwörter (mit „;“ getrennt), Bewertung (0–5), Autor, Copyright und Aufnahmedatum. PanePilot schreibt jedes Feld an alle üblichen Stellen (XMP, IPTC, EXIF), damit z. B. digiKam oder der Bildbetrachter es finden.
- **Kamera, Objektiv, Belichtung, Blende, ISO, Brennweite, Blitz, Ausrichtung und GPS** lassen sich nicht ändern, aber mit `< entfernen >` löschen – etwa die GPS-Position, bevor man Fotos weitergibt. **Auf Karte zeigen** öffnet die Position in OpenStreetMap.
- **Eigene Felder** legt man wie bei der Musik über die Spaltenköpfe an. Sie werden als XMP gespeichert; andere Programme lesen sie meist mit, zeigen sie aber nicht in ihrer normalen Ansicht – für Dinge, die überall sichtbar sein sollen, sind die Schlagwörter besser.
- Statt des Covers zeigt die Seitenleiste ein **Vorschaubild**.
- **Konverter** bei Fotos: Tag → Dateiname, Dateiname → Tag, Tag → Tag, Tag → Textdatei/CSV, Textdatei → Tag und **Datum verschieben …**.
  - Platzhalter: `%datetaken%`, `%make%`, `%model%`, `%lens%`, `%iso%`, `%title%`, `%rating%`, `%author%` …, dazu `%camera%`, `%width%`, `%height%`.
  - `$date(%datetaken%,JJJJ-MM-TT_hhmmss)` formt das Datum um, z. B. zu `2026-11-08_150012`. Fehlt das Aufnahmedatum, wird das Änderungsdatum der Datei genommen.
  - **Datum verschieben …** verschiebt das Aufnahmedatum um Tage, Stunden, Minuten und Sekunden, z. B. wenn die Kamera-Uhr falsch ging. Fotos ohne Aufnahmedatum werden übersprungen.

## Videos
Enthält der Ordner Videos, zeigt der Meta-Wizard deren Metadaten. Sind mehrere Arten gemischt, wählt man oben mit **„Musik | Fotos | Videos“** aus, was angezeigt wird; vorgewählt ist die Art mit den meisten Dateien. Dateien mit der Endung `.mp4` zählen immer als Video, `.m4a` als Musik.
- **Lesen und schreiben**: MP4, MOV, M4V, 3GP und WMV. **MKV und WebM** nur, wenn das Paket **mkvtoolnix** installiert ist (`sudo apt install mkvtoolnix`), sonst nur lesen. **AVI** und **MTS/M2TS** (Camcorder) werden nur gelesen.
- **Bearbeiten**: Titel, Beschreibung, Autor, Copyright, Genre, Jahr und Aufnahmedatum, dazu **eigene Felder** wie bei der Musik.
- **Dauer, Auflösung, Bildrate, Video- und Audio-Codec und Bitrate** liest PanePilot mit dem Programm **ffmpeg** (`sudo apt install ffmpeg`). Ohne ffmpeg fehlen diese Angaben.
- **Aufnahmedatum und GPS**: Bei MP4/MOV lässt sich das Aufnahmedatum nur mit **exiftool** ändern und GPS nur damit entfernen (`sudo apt install libimage-exiftool-perl`). Bei MKV/WebM ändert mkvtoolnix das Datum. Bei WMV bleibt das Datum unverändert. **Auf Karte zeigen** öffnet die Position in OpenStreetMap.
- **Endung passt nicht zum Inhalt**: PanePilot erkennt das tatsächliche Format am Dateianfang, nicht an der Endung. Ist z. B. ein MKV-Video als `.mp4` gespeichert, wird es trotzdem richtig gelesen und geschrieben. Die Spalte **Format** zeigt dann zuerst das tatsächliche Format und in Klammern die Endung der Datei, z. B. **„MKV (.mp4)“**, und die Seitenleiste weist darauf hin. Passen Format und Endung zusammen, steht dort wie gewohnt nur das Format, z. B. „MP4“. Am besten benennt man solche Dateien um, damit die Endung stimmt.
- **Vorschaubild (Poster)**: Die Seitenleiste zeigt das im Video gespeicherte Vorschaubild. Fehlt es, zeigt sie ein Standbild aus dem Video (bei etwa 10 % der Laufzeit). Per Rechtsklick lässt sich das Vorschaubild ersetzen, entfernen oder speichern; **„Standbild als Vorschaubild übernehmen“** speichert das gezeigte Standbild als Poster ins Video.
- **Konverter** bei Videos: wie bei Fotos, also Tag → Dateiname, Dateiname → Tag, Tag → Tag, Tag → Textdatei/CSV, Textdatei → Tag und **Datum verschieben …**.
  - Platzhalter: `%datetaken%`, `%title%`, `%author%`, `%genre%`, `%year%` …, dazu `%duration%`, `%resolution%`, `%width%`, `%height%`, `%fps%`, `%codec%` und `%format%`.
  - `$date(%datetaken%,JJJJ-MM-TT_hhmmss)` ergibt z. B. `2026-11-08_150012.mp4`.
  - Das Aufnahmedatum steht in Videos meist in Weltzeit (UTC); PanePilot zeigt es in der Ortszeit des Rechners an.

Welche Zusatzprogramme PanePilot nutzt, steht im Kapitel **Zusatzprogramme**.
