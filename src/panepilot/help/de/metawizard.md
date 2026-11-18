# Meta-Wizard

**Meta-Wizard …** (Strg+T) bearbeitet die Tags von Musikdateien (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV), ähnlich wie MP3TAG, und die Metadaten von Fotos, Videos und Dokumenten (siehe unten).

## Grundlagen
- Die Titelliste zeigt die Dateien des aktuellen Ordners mit ihren Tags. Spalten wählt man per Rechtsklick auf die Spaltenköpfe, dort lassen sich auch eigene Felder anlegen.
- In der Seitenleiste bearbeitet man die markierten Titel. Bei mehreren Titeln mit unterschiedlichen Werten steht dort `< beibehalten >`: Was man nicht anfasst, bleibt in jeder Datei, wie es ist.
- Änderungen sind zuerst nur **vorgemerkt** und grün markiert. Erst **Tag speichern** schreibt sie in die Dateien. **Rückgängig** macht das letzte Speichern rückgängig.
- **Cover**: Bild hineinziehen oder Rechtsklick auf das Cover zum Laden, Speichern oder Entfernen.

## Konverter
- **Dateiname → Tag**, **Tag → Dateiname**, **Tag → Tag**: mit Formatstrings wie `%track% - %title%`. Es gibt eine Vorschau und Vorlagen.
  - Beispiele für **Dateiname → Tag**. `%dummy%` überspringt einen Teil des Namens; eigene Felder schreibt man wie Platzhalter, z. B. `%Season%`:
    - `01 - Intro.mp3` → `%track% - %title%`
    - `Alien (1979).mkv` → `%title% (%year%)`
    - `Battlestar Galactica (2003) - S01E09 - Tigh Me Up.mkv` → `%dummy% - S%Season%E%Episode% - %title%` (Season „01“, Episode „09“, Titel „Tigh Me Up“)
- **Tag → Textdatei/CSV** und **Textdatei → Tag**: zum Bearbeiten in LibreOffice oder zum Übernehmen einer Titelliste aus dem Internet. Das Zuordnungsfenster mit Platzhaltern gleicht fehlende Zeilen aus.
  - **Tabelle aus LibreOffice Calc:** eine Spalte **„Dateiname“** (genauer Name mit Endung) und weitere Spalten mit Überschriften wie „Titel“, „Jahr“ oder eigenen Feldnamen. Speichern als **Text CSV**, Feldtrenner Semikolon oder Komma, Zeichensatz UTF-8, **ohne „Feste Spaltenbreite“**. PanePilot ordnet die Zeilen dann über den Dateinamen zu.
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
- **Audiospuren und Untertitel**: Die wählbaren Spalten **Audiospuren** und **Untertitel** zeigen die Sprachen der enthaltenen Spuren, so wie sie in der Datei stehen, z. B. `deu, eng` bzw. `eng (forced)`; `?` heißt „ohne Sprachangabe“. Fährt man mit der Maus darüber, erscheint je Spur eine Zeile mit ausgeschriebener Sprache, Format und Kennzeichen, z. B. „deu (Deutsch) – AC-3 5.1 – Standard“. Die Angaben stammen von ffmpeg und lassen sich hier nur ansehen, nicht ändern. Untertitel als eigene Datei (`.srt` neben dem Video) zählen nicht mit.
- **Endung passt nicht zum Inhalt**: PanePilot erkennt das tatsächliche Format am Dateianfang, nicht an der Endung. Ist z. B. ein MKV-Video als `.mp4` gespeichert, wird es trotzdem richtig gelesen und geschrieben. Die Spalte **Format** zeigt dann zuerst das tatsächliche Format und in Klammern die Endung der Datei, z. B. **„MKV (.mp4)“**. Damit solche Dateien in langen Listen auffallen, steht die ganze Zeile in **blauer, fetter Schrift**, und die Seitenleiste weist darauf hin (eine vorgemerkte Änderung färbt die Zeile grün, ein Fehler rot). Passen Format und Endung zusammen, steht dort wie gewohnt nur das Format, z. B. „MP4“. Am besten benennt man solche Dateien um, damit die Endung stimmt.
- **Vorschaubild (Poster)**: Die Seitenleiste zeigt das im Video gespeicherte Vorschaubild. Fehlt es, zeigt sie ein Standbild aus dem Video (bei etwa 10 % der Laufzeit). Per Rechtsklick lässt sich das Vorschaubild ersetzen, entfernen oder speichern; **„Standbild als Vorschaubild übernehmen“** speichert das gezeigte Standbild als Poster ins Video.
- **Konverter** bei Videos: wie bei Fotos, also Tag → Dateiname, Dateiname → Tag, Tag → Tag, Tag → Textdatei/CSV, Textdatei → Tag und **Datum verschieben …**.
  - Platzhalter: `%datetaken%`, `%title%`, `%author%`, `%genre%`, `%year%` …, dazu `%duration%`, `%resolution%`, `%width%`, `%height%`, `%fps%`, `%codec%`, `%audiolang%`, `%sublang%` und `%format%`.
  - `$date(%datetaken%,JJJJ-MM-TT_hhmmss)` ergibt z. B. `2026-11-08_150012.mp4`.
  - Das Aufnahmedatum steht in Videos meist in Weltzeit (UTC); PanePilot zeigt es in der Ortszeit des Rechners an.

## Online-Daten für Filme
Im Video-Modus holt der Knopf **„Online-Daten (Filme, Serien) …“** Titel, Jahr, Genre, Inhaltsangabe, Regie und Poster aus dem Internet, für die markierten Videos (ohne Markierung für alle angezeigten).
- **Woher PanePilot weiß, welcher Film es ist**, in dieser Reihenfolge:
  1. eigene Felder `imdbid` bzw. `themoviedb`
  2. Kennung im Dateinamen im Jellyfin-Stil, z. B. `Alien (1979) [imdbid-tt0078748].mkv` oder `[tmdbid-348]`
  3. sonst Suche über Titel und Jahr aus dem Dateinamen, z. B. `Alien (1979).mkv`. Gibt es genau einen Treffer mit diesem Jahr, wird er genommen, sonst wählst du den Film aus einer Liste (oder „Überspringen“).
- **Quellen:**
  - **TMDb** (The Movie Database), wenn in den Einstellungen ein API-Schlüssel eingetragen ist: alle Angaben einschließlich Inhaltsangabe und Poster.
  - **Wikidata**, wenn kein Schlüssel eingetragen ist: kein Konto nötig, aber ohne Inhaltsangabe und Poster.
- **Sprache:** Titel, Inhaltsangabe und Genre kommen in der **Programmsprache** (bei Fränkisch und Sächsisch auf Deutsch). Gibt es keine Fassung in dieser Sprache, wird Englisch genommen.
- **Übersicht:** Vor dem Übernehmen zeigt PanePilot je Film „Feld – bisher – neu“. Angehakt sind nur Felder, die bisher leer sind; vorhandene Werte werden nur überschrieben, wenn du das Häkchen setzt. Die Knöpfe „Alle Felder“ und „Nur leere Felder“ setzen die Häkchen für alle Filme.
- **Übernehmen** merkt die Werte grün vor; geschrieben wird erst mit **„Tag speichern“**, „Rückgängig“ funktioniert wie immer.
- Fehlt eine Kennung, wird sie ergänzt: Ein Film mit `imdbid` bekommt auch `themoviedb` und umgekehrt. Weicht der Originaltitel vom Titel ab, kommt er ins Feld `originaltitle`. Das Poster (etwa 500 Pixel breit) wird bei MP4, MKV und WMV als Cover gespeichert.
- AVI-Dateien lassen sich nicht beschriften; sie erscheinen in der Übersicht mit „Format nur lesbar“.

### TMDb-API-Schlüssel beantragen
1. Auf **themoviedb.org** ein kostenloses Konto anlegen und die E-Mail bestätigen.
2. Oben rechts auf das Profilbild → **Einstellungen** → **API** und dort einen Schlüssel beantragen („Developer“, private Nutzung). Die Angaben zur Anwendung sind formlos, z. B. „PanePilot, private Filmsammlung“.
3. Den **API-Schlüssel** (32 Zeichen) oder das lange **API-Lesezugriffstoken** kopieren.
4. In PanePilot: **Einstellungen → Meta-Wizard → Online-Daten für Filme**, Schlüssel einfügen, **„Prüfen“**, dann **OK**.

Der Schlüssel wird nur in deinem Schlüsselbund gespeichert, nicht in den Einstellungsdateien. Dieses Produkt nutzt die TMDb-API, ist aber nicht von TMDb unterstützt oder zertifiziert.

## Spuren bearbeiten (MKV und MP4)
Im Video-Modus öffnet **„Spuren …“** für die markierten MKV- und MP4-Videos eine Tabelle aller Spuren: Video, Ton und Untertitel, jeweils mit Format, Sprache, Name und den Kennzeichen „Standard“ und „Erzwungen“.
- **Sprache:** aus der Liste wählen, z. B. „Deutsch (ger)“, oder einen Code eintippen. In der Spalte „Audiospuren“ steht danach `ger` statt `?`.
- **Name:** frei eintragen oder mit **„Namen vorschlagen“** bilden lassen, z. B. „Deutsch AC3 5.1“ (für die markierten Zeilen, sonst für alle). Diesen Namen zeigen Player wie VLC statt „Titel 1“.
- **Standard** ist die Spur, die ein Player zuerst nimmt; **Erzwungen** (forced) zeigt Untertitel nur für fremdsprachige Stellen. Bei Videospuren lässt sich nur der Name ändern.
- **Mehrere Videos auf einmal:** Die Spuren werden nach Nummer zusammengefasst („Tonspur 1“, „Untertitel 1“ …). Eine Änderung gilt für diese Spur in allen markierten Videos. Unterschiedliche Werte erscheinen als „verschieden“ und bleiben unverändert, solange man sie nicht ändert. Videos ohne die Spur werden ausgelassen und vorher aufgelistet.
- **Speichern:** „Übernehmen“ fragt noch einmal nach und schreibt dann **sofort** in die Dateien (mit mkvpropedit, in Sekunden, auch auf dem NAS). „Rückgängig“ gibt es dafür nicht.
- Bei **MKV** ist **mkvtoolnix** nötig (`sudo apt install mkvtoolnix`).
- **MP4** (auch M4V und MOV):
  - Die **Sprache** wird direkt in der Datei geändert, in Sekunden. MP4 verlangt dabei die Codes `deu`, `fra`, `nld` … statt `ger`, `fre`, `dut`; PanePilot wandelt automatisch um.
  - **Spurname** und **„Standard“** gehen nur über eine neue Datei: PanePilot packt sie mit ffmpeg neu (ohne Neukodieren, ohne Qualitätsverlust). Das dauert etwa so lange wie das Kopieren der Datei und braucht vorübergehend genauso viel freien Platz; eine Rückfrage weist vorher darauf hin, der Fortschrittsbalken hat „Abbrechen“. Tags, eigene Felder (z. B. `imdbid`, `Season`) und Cover übernimmt PanePilot; die alte Datei wird erst ersetzt, wenn die neue geprüft ist.
  - **„Erzwungen“** ist bei MP4 ausgegraut, weil MP4 das kaum unterstützt.

- **Spuren entfernen:** In der Spalte **„Entfernen“** Ton- oder Untertitelspuren anhaken. Dafür entsteht eine **neue Datei** `Film-Kopie.mkv` (bzw. `.mp4`) im selben Ordner, das **Original bleibt unverändert** – was danach mit ihm geschieht, entscheidest du. Die Videospur und die letzte Tonspur lassen sich nicht entfernen; war die entfernte Spur „Standard“, übernimmt das die nächste.
- **Untertitel exportieren:** Beim Entfernen ist **„Untertitel vor dem Entfernen als Datei speichern“** vorgehakt. Der Knopf **„Untertitel exportieren“** speichert die markierten (sonst alle) Untertitel, ohne sie zu entfernen. Text-Untertitel werden zu `.srt`, ASS-Untertitel zu `.ass`, Bild-Untertitel bleiben im Originalformat (`.sup` bzw. `.idx` + `.sub`). Die Dateien heißen wie bei Jellyfin üblich, z. B. `Film (2001).ger.srt` oder `Film (2001).ger.forced.srt`.

## Format wechseln
**„Format wechseln …“** packt die markierten Videos ohne Neukodieren (ohne Qualitätsverlust) in ein anderes Format: **MP4, M4V, MOV und AVI → MKV** oder **MKV → MP4**.
- Es entsteht eine **neue Datei** im selben Ordner, z. B. `Film.mkv` neben `Film.mp4`; gibt es die schon, `Film-Kopie.mkv`. Das Original bleibt unverändert.
- Übernommen werden Titel, Jahr, Genre, Beschreibung, Autor, alle eigenen Felder (z. B. `imdbid`, `Season`), Cover, Sprachen und Namen der Spuren sowie Kapitel.
- MP4 kann keine Bild-Untertitel (PGS, VobSub) und Tonformate wie DTS oder TrueHD aufnehmen; solche Dateien werden ausgelassen und genannt. Text-Untertitel werden für MP4 umgewandelt (Formatierungen gehen verloren).
- Das dauert etwa so lange wie das Kopieren und braucht genauso viel freien Platz; „Abbrechen“ verwirft die gerade entstehende Datei. Für MKV als Ziel ist mkvtoolnix nötig, für MP4 ffmpeg.
- Untertiteldateien neben dem Video (`Film.eng.srt`) bleiben unberührt und passen weiter.

## Online-Daten für Serien
**„Online-Daten (Filme, Serien) …“** erkennt Folgen am Muster **`S01E02`** im Dateinamen (auch `s1e2` oder `1x02`).
- **Serienname:** aus dem Ordner, z. B. `Breaking Bad/Staffel 1/Breaking Bad - S01E02.mkv` oder `Breaking Bad (2008) [tmdbid-1396]/S01E02.mkv`; sonst aus dem Dateinamen vor `S01E02`.
- Die Serie wird **einmal je Serie** gesucht; bei mehreren Treffern wählt man sie einmal aus, das gilt dann für alle Folgen.
- **Felder:** Titel (Episodentitel), `Series`, `Season` und `Episode` (zweistellig, z. B. `01`), Jahr der Erstausstrahlung, Inhalt der Folge, Genre der Serie, Staffelposter als Cover und `themoviedb` (Kennung der Serie). Bei MP4 kommen Serie, Staffel und Folge zusätzlich in die iTunes-Standardfelder.
- Serien gibt es nur mit **TMDb-Schlüssel**; ohne Schlüssel erscheint ein Hinweis, Filme kommen weiterhin von Wikidata.
- Mit **Tag → Dateiname** und `%Series% - S%Season%E%Episode% - %title%` lassen sich die Folgen danach einheitlich benennen, z. B. `Breaking Bad - S01E02 - Die Katze ist im Sack.mkv`.

## Dokumente
Auch Office-Dateien und PDFs lassen sich im Meta-Wizard beschriften. Bei gemischten Ordnern wählt man oben **„Dokumente“** im Umschalter **„Musik | Fotos | Videos | Dokumente“**. Zusatzprogramme sind dafür nicht nötig.
- **Lesen und schreiben**: Word, Excel und PowerPoint (DOCX, XLSX, PPTX, auch DOCM, XLSM, PPTM), LibreOffice/OpenDocument (ODT, ODS, ODP, ODG) und **PDF**.
- **Nur lesen**: die alten Office-Formate **DOC, XLS, PPT**, **verschlüsselte PDFs** und **digital signierte PDFs**. Bei signierten PDFs würde jede Änderung die Signatur ungültig machen; die Seitenleiste weist darauf hin.
- **Bearbeiten**: Titel, Thema, Autor, Schlagwörter, Beschreibung, Kategorie und Sprache, dazu **eigene Felder** über „Feld einfügen“. Sie landen in den „benutzerdefinierten Eigenschaften“, die auch Word und LibreOffice unter **Datei → Eigenschaften** zeigen. Bei PDF gibt es keine Beschreibung und keine Kategorie, bei OpenDocument keine Kategorie.
- **Nur zum Ansehen**: Erstellt am, Geändert am, Zuletzt gespeichert von, Anwendung (bei PDF Programm und Erzeuger), Seiten, Wörter und PDF-Version, soweit sie in der Datei stehen. Das Speichern der Metadaten ändert diese Angaben nicht.
- **Wohin geschrieben wird**: bei Office in die Dokumenteigenschaften der Datei, bei PDF in die Dokumentinformationen und zusätzlich in die XMP-Metadaten, falls die PDF welche hat. Der Inhalt der Datei bleibt unverändert.
- **Schlagwörter** trennt man mit Semikolon, z. B. `Steuer; 2026`.
- **Vorschau**: Bei PDF zeigt die Seitenleiste die erste Seite, bei Office-Dateien das Vorschaubild, das Word, Excel oder LibreOffice in der Datei abgelegt haben (sofern vorhanden).
- **Konverter**: Tag → Dateiname, Dateiname → Tag, Tag → Tag, Tag → Textdatei/CSV und Textdatei → Tag.
  - Platzhalter: `%title%`, `%subject%`, `%author%`, `%keywords%`, `%created%`, `%modified%`, `%application%`, `%pages%`, `%words%` und `%format%`.
  - `$date(%created%,JJJJ-MM-TT) %title%` ergibt z. B. `2026-11-17 Angebot.pdf`.

Welche Zusatzprogramme PanePilot nutzt, steht im Kapitel **Zusatzprogramme**.
