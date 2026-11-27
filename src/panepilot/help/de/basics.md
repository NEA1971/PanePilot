# Bedienung

PanePilot zeigt zwei Dateifenster (Panels) nebeneinander. Eines davon ist **aktiv**, erkennbar an der farbigen Pfadzeile. Die meisten Befehle gelten für die markierten Einträge im aktiven Panel. Kopieren und Verschieben gehen immer **ins andere Panel**.

## Navigieren
- **Doppelklick** oder **Enter** öffnet einen Ordner bzw. öffnet eine Datei mit ihrem Standardprogramm.
- **Rücktaste** geht eine Ebene höher. Die Maustasten „Zurück“ und „Vor“ funktionieren wie im Browser.
- **Tab** wechselt zwischen den Panels.
- In die **Pfadzeile** kann man einen Pfad direkt eintippen.
- Im Menü **Navigation**: gleicher Ordner im anderen Panel, Panels tauschen, Zurück, Vor.
- **Favoriten-Menü** (Alt+↑ oder Menü Favoriten): zeigt die Favoriten des Satzes der aktiven Seite als Aufklappmenü am aktiven Fenster – Favoritenordner als Untermenüs, Trennlinien als Linien; mit Pfeiltasten, Enter und Esc bedienbar. Ein Ordner öffnet sich im aktiven Fenster, eine Datei mit ihrem Standardprogramm. Die Taste lässt sich unter Einstellungen → Tastenkürzel ändern.
- **Zuletzt besuchte Ordner**: der Pfeil rechts in der Pfadzeile (oder Alt+↓) zeigt die letzten 20 Ordner beider Fenster, neueste oben; die Liste wird beim Beenden gemerkt.

## Reiter
- Jedes Fenster kann mehrere **Reiter** haben: **Strg+T** öffnet einen neuen Reiter mit dem aktuellen Ordner, **Strg+W** schließt ihn, **Strg+Tab** / **Strg+Umschalt+Tab** wechseln.
- Neuer Reiter auch mit der **mittleren Maustaste** oder **Strg+Doppelklick** auf einen Ordner, über **„In neuem Reiter öffnen“** im Kontextmenü (auch für mehrere markierte Ordner) und per Doppelklick auf die freie Reiterleiste. Die mittlere Maustaste auf einem Reiter schließt ihn; Reiter lassen sich per Ziehen umsortieren.
- Jeder Reiter hat seinen eigenen Ordner, Verlauf, Sortierung, Filter und Ansicht (Details/Symbole); Spalten und Seitenleiste gelten für das ganze Fenster.
- **Rechtsklick auf einen Reiter**: Neuer Reiter, Schließen, Andere schließen, Sperren/Entsperren, Im anderen Fenster öffnen. Ein **gesperrter Reiter** (🔒) bleibt stehen – wechselt man darin den Ordner, öffnet sich ein neuer Reiter.
- Die Reiterleiste erscheint ab dem zweiten Reiter (Einstellungen → Dateiansicht → Reiter: „immer anzeigen“). Während Suche, Umbenennen, Meta-Wizard, Synchronisieren oder einer Server-Verbindung sind die Reiter dieses Fensters gesperrt. Alle Reiter werden beim Beenden gemerkt. Der Knopf **„Reiter“** in der Werkzeugleiste schaltet „Reiterleiste immer anzeigen“ ein und aus; sein Pfeil-Menü enthält In neuem Reiter öffnen, Neuer/Nächster/Vorheriger Reiter, Reiter schließen und Reiter sperren.

## Dateien bearbeiten
- **Kopieren / Verschieben** ins andere Panel (F5 / F6) fragt vorher nach, die Varianten „ohne Rückfrage“ legen sofort los. Ziehen mit der Maus geht ebenfalls, auch von und nach Nautilus.
- **Umbenennen** (F2), **Neuer Ordner** (F7), **Neue Textdatei** (Umschalt+F4), **In den Papierkorb** (F8), **Endgültig löschen**. Beim Umbenennen zeigt das Eingabefeld immer den kompletten Namen mit Endung – auch in der Spalte „Name (ohne Endung)“. Vorab markiert ist der Teil vor der Endung; die Endung lässt sich mit ändern.
- **Zwischenablage**: Kopieren, Ausschneiden, Einfügen (Strg+C/X/V), auch zusammen mit anderen Programmen.
- **Pfade und Namen in die Zwischenablage** (Menü Bearbeiten, Rechtsklick → „In die Zwischenablage“ oder Pfeil am Knopf „Kopieren“): Dateipfad (Alt+Einfg), Dateiname (Alt+Umschalt+Einfg), Dateiname ohne Erweiterung, Ordnerpfad, Dateipfad als Adresse (`file:///…`) und Details (Name, Größe in Bytes, Datum, Typ – durch Tabulator getrennt, z. B. zum Einfügen in Excel). Bei mehreren markierten Dateien steht jede in einer eigenen Zeile.
- **Duplizieren** (Strg+D, auch im Rechtsklick-Menü): legt von den markierten Dateien und Ordnern im selben Ordner eine Kopie an, ohne Rückfrage – `Bericht.docx` wird zu `Bericht-Kopie.docx`, beim nächsten Mal `Bericht-Kopie-2.docx`. Die Kopien sind danach markiert, z. B. zum Umbenennen mit F2. Auf FTP-/SFTP-Servern nicht möglich.
- **Fenster übereinander** (Ansicht → „Fenster übereinander“, Strg+Umschalt+H): stellt die beiden Fenster übereinander statt nebeneinander. Jedes Fenster behält seine Seitenleiste links daneben, die Knopfleiste liegt waagerecht dazwischen. Die Aufteilung wird für beide Anordnungen getrennt gemerkt.
- **Aktualisieren** (Strg+R, auch ganz unten im Rechtsklick-Menü): liest den angezeigten Ordner neu ein; die Markierung bleibt erhalten.
- **Öffnen mit**: Rechtsklick auf eine Datei zeigt die passenden Programme, „Andere Anwendung …“ alle.
- **Archive** (Knopf „Archiv“ bzw. Rechtsklick → „Archiv ▸“): **Öffnen**, **Hier entpacken**, **Entpacken nach …**, **Entpacken nach „Name“** (eigener Ordner) und **Archiv erstellen …**. Ein Klick auf den Knopf öffnet das markierte Archiv; ist keins markiert, startet „Archiv erstellen …“.
- **Archiv wie einen Ordner:** Doppelklick oder Enter auf ein zip-, tar-, 7z- oder rar-Archiv zeigt seinen Inhalt im Fenster (Pfad z. B. `…/Fotos.zip/Urlaub`); „..“ führt wieder hinaus. Dateien darin lassen sich öffnen und mit F5 oder Ziehen ins andere Fenster kopieren – das entpackt sie.
- **In Archive schreiben** (ZIP und TAR ohne Zusatzprogramm, 7z mit 7-Zip; RAR bleibt nur lesbar): **F5** oder Ziehen aus dem anderen Fenster kopiert hinein (bei gleichen Namen kommt dieselbe Rückfrage wie beim Kopieren), **F6** verschiebt hinein (Originale danach in den Papierkorb) oder heraus (entpacken, dann im Archiv löschen), **F7** legt einen Ordner an, **F2** benennt um, **F8**/Entf löscht – im Archiv **endgültig**, mit Rückfrage. PanePilot schreibt dabei zuerst eine Kopie neben das Archiv und ersetzt das Original erst, wenn alles geklappt hat; bei Fehler oder Abbruch bleibt es unverändert. Hast du eine Datei aus dem Archiv geöffnet und speicherst sie, fragt PanePilot, ob die Änderung zurück ins Archiv soll (solange PanePilot läuft). Passwortgeschützte Archive lassen sich mit 7-Zip und dem eingegebenen Passwort beschreiben. Bei passwortgeschützten Archiven fragt PanePilot nach dem Passwort (wird nicht gespeichert). Wer Archive lieber mit dem Standardprogramm öffnet, stellt das unter Einstellungen → Dateiansicht → Archive um. 7z und rar brauchen 7zip bzw. unrar, AES-verschlüsselte ZIPs ebenfalls 7zip.
- **Eigenschaften** (Alt+Enter) zeigt Größe, Rechte, Daten und bei Musik, Fotos, Videos und Dokumenten die Metadaten.
- **Terminal hier öffnen** (Menü Datei oder Rechtsklick): öffnet das Standard-Terminal im angezeigten Ordner, nach Rechtsklick auf einen Ordner in diesem.
- **Verzeichnisliste erstellen …** (Menü Datei oder Rechtsklick): schreibt eine eingerückte Liste des Ordners mit Größen und Änderungsdatum in eine Textdatei. Man wählt Tiefe, ob Dateien und versteckte Einträge dazugehören und ob die Liste danach geöffnet wird.

## Ansicht
- **Filter** (Menü Ansicht): zeigt nur passende Einträge, z. B. `*.mp3`. Mehrere Muster trennt man mit Semikolon oder Komma, z. B. `*.mkv;*.mp4`. Ein aktiver Filter färbt die Pfadzeile rot.
- **Versteckte Dateien**, **Ein-Fenster-Ansicht**, Knopfleiste, F-Tasten-Leiste und Symbolleiste lassen sich im Menü **Ansicht** ein- und ausschalten.
- Spalten: Rechtsklick auf die Spaltenköpfe. Reihenfolge und Breite stellt man direkt durch Ziehen ein (siehe [Einstellungen](settings.md)).

## Schnellansicht
- Knopf **„Schnellansicht“** (Lupe über einem Blatt, rechts neben „Ansicht“) oder **Ansicht → Schnellansicht**: Das **andere Fenster** zeigt statt der Dateiliste die markierte Datei. Beim Weiterblättern mit den Pfeiltasten folgt die Vorschau. Noch ein Klick oder **Esc** bringt die Liste zurück. Eine Taste ist ab Werk nicht belegt – unter Einstellungen → Tastenkürzel bzw. F-Tasten frei wählbar.
- Gezeigt werden: **Text** (der Anfang bis 1 MB), **Bilder** (eingepasst, Mausrad zoomt), **PDF** (alle Seiten untereinander), **Videos** (ein Standbild mit Dauer, Auflösung und Spuren), **Musik** (Cover und Tags), **LibreOffice- und Microsoft-Dokumente** (Writer/Word als Text, Calc/Excel als Tabelle mit einem Reiter je Blatt – die ersten 500 Zeilen –, Impress/PowerPoint Folie für Folie als Text). Bei anderen Dateien Art, Größe und Datum, bei Ordnern die Zahl der Einträge.
- Die Schnellansicht braucht beide Fenster; in der Ein-Fenster-Ansicht oder wenn das andere Fenster gerade etwas anderes zeigt (z. B. den Meta-Wizard), geht sie nicht.

## Auswahl, Ordnergrößen, Vergleichen, Datum
- **Auswahl nach Muster** (Menü Bearbeiten): **Num +** erweitert die Auswahl, **Num −** verringert sie – vorbelegt ist die Endung der aktuellen Datei, z. B. `*.jpg`, mehrere Muster mit `;`, die letzten Muster stehen zur Auswahl, mit „Auch Ordner“ zählen Ordner mit. **Num \*** kehrt die Auswahl um, **Alt+Num +** markiert alle Dateien mit derselben Endung wie die aktuelle.
- **Ordnergrößen:** **Leertaste** auf einem Ordner zeigt seine Größe in der Spalte „Größe“. **Ansicht → Alle Ordnergrößen berechnen** (Alt+Umschalt+Enter) macht das für alle Ordner im Fenster, im Hintergrund – **Esc** bricht ab. Die Werte bleiben, bis du den Ordner verlässt oder „Aktualisieren“ wählst; die Summe der Markierung in der Statuszeile zählt sie mit.
- **Dateien vergleichen …** (Rechtsklick oder Menü Datei, Strg+Umschalt+C): vergleicht **zwei markierte Dateien** – beide in einem Fenster oder je eine links und rechts. Textdateien erscheinen nebeneinander mit farbigen Unterschieden (gelb geändert, rot nur links, grün nur rechts), beide Seiten scrollen gemeinsam, **▲ / ▼** (Alt+↑ / Alt+↓) springen zum vorherigen/nächsten Unterschied. PDF-, LibreOffice- und Microsoft-Dokumente werden über ihren Text verglichen. Bei anderen Dateien meldet PanePilot „identisch“ oder die Stelle der ersten Abweichung.
- **Datum ändern …** (Rechtsklick oder Menü Datei): setzt das Änderungsdatum auf ein festes Datum, auf jetzt, auf das **Aufnahmedatum** (Fotos/Videos) oder auf ein Datum im **Dateinamen** (z. B. `IMG_20240512_143012.jpg`). Die Vorschau zeigt alt → neu; Dateien ohne passendes Datum bleiben, wie sie sind. Mit „Auch Unterordner“ gilt es für alles darin. Das Erstellungsdatum lässt sich unter Linux nicht setzen.
- **Rechte für Unterordner:** Eigenschaften → Berechtigungen → „Auch für Unterordner und enthaltene Dateien“. Ordner bekommen dabei das Recht „Ausführen“, damit man sie weiter öffnen kann.

## Gemeinsame Seitenleiste
- **Ansicht → Gemeinsame Seitenleiste** zeigt statt zwei Seitenleisten **eine ganz links** über die volle Höhe – nebeneinander wie übereinander.
- Sie gilt immer für das **aktive Fenster**: Klickst du ins andere Fenster, zeigt der Ordnerbaum dessen Ordner und Favoriten öffnen dort. Ansicht und Favoritensatz bleiben dabei gleich.
- **Werkzeuge** (Umbenennen, Suche, Prüfsummen, Meta-Wizard) bleiben bei dem Fenster, in dem sie gestartet wurden, bis du sie schließt.
- Im Menü „Ansicht“ gibt es dann nur einen Eintrag „Seitenleiste“. Die Breite wird je Anordnung gemerkt.

## Symbolansicht
- **Knopf „Ansicht“** in der Symbolleiste (über „Symbolleiste anpassen“): ein Klick wechselt zwischen Details und der zuletzt benutzten Symbolgröße, der Pfeil daneben zeigt Große, Mittelgroße und Kleine Symbole sowie Details; der Punkt markiert die aktuelle Ansicht.
- **Ansicht → Symbolansicht** (Strg+Umschalt+I) zeigt das aktive Fenster mit großen Symbolen statt als Liste; jedes Fenster merkt sich seine Ansicht.
- Drei Größen über **Ansicht → Symbolgröße** oder **Strg+Mausrad**.
- **Vorschaubilder:** Bilder, die erste Seite von PDFs, das Cover von Musikdateien und das Poster von Videos (sonst ein Bild aus dem Film). Vorschaubilder, die schon im gemeinsamen Zwischenspeicher `~/.cache/thumbnails` liegen (z. B. von Nautilus), werden sofort genutzt, fehlende im Hintergrund erzeugt und dort abgelegt.
- Markieren, Tastatur, Kopieren, Ziehen und Kontextmenü funktionieren wie in der Liste. Sortiert wird über **Ansicht → Sortieren nach**.

## Favoriten
- **Zu Favoriten hinzufügen** merkt sich den aktuellen Ordner. Favoriten lassen sich in Ordnern gruppieren und erscheinen in der Seitenleiste und im Menü **Favoriten**.

Siehe auch: [Seitenleisten](sidebars.md) · [Tastenkürzel](shortcuts.md)

## Windows
- **Installieren:** `PanePilot-…-windows-x64-setup.exe` installiert nach `C:\Program Files\PanePilot` (mit Administratorrechten), mit Startmenü-Eintrag und auf Wunsch Desktop-Symbol; deinstalliert wird über „Apps & Features“. Alternativ gibt es das **portable ZIP** zum Entpacken. Weil PanePilot nicht signiert ist, warnt Windows beim ersten Start: „Weitere Informationen“ → „Trotzdem ausführen“. Einstellungen liegen unter `%APPDATA%\PanePilot`.
- **Papierkorb:** wie unter Linux – anzeigen, wiederherstellen, endgültig löschen und leeren arbeiten mit dem Windows-Papierkorb.
- **Öffnen mit:** zeigt die für den Dateityp registrierten Programme; „Andere Anwendung …“ öffnet das Windows-Fenster „Öffnen mit“.
- **Laufwerke:** Im Ordnerbaum stehen unter **Dieser PC** alle Laufwerke mit Bezeichnung, auch Netzlaufwerke. **Datei → Netzlaufwerk verbinden … / trennen …** (auch per Rechtsklick im Ordnerbaum) öffnet das Windows-Fenster dafür.
- **Netzwerk:** Zwei Wege führen zu einer Freigabe. (1) In die Pfadzeile `\\NAS` eingeben – dann erscheinen die Freigaben des Servers als Ordner; `\\NAS\Freigabe` öffnet die Freigabe direkt. (2) Im Ordnerbaum unter **Netzwerk**: dort stehen die Rechner, die Windows im Netz findet, und deine selbst eingetragenen Server (Rechtsklick auf „Netzwerk“ → **Server hinzufügen …**, auf einem eigenen Server → **Server entfernen**). Ein Klick auf einen Server zeigt seine Freigaben; jeder Server steht nur einmal da, egal wie er gefunden wurde. Verlangt der Server eine Anmeldung, öffnet sich das Windows-Anmeldefenster (mit „Anmeldedaten speichern“). Rechtsklick auf eine Freigabe → **Als Netzlaufwerk verbinden …** gibt ihr einen Laufwerksbuchstaben. Die Suche im Netz lässt sich unter Einstellungen → Dateiansicht → Netzwerk abschalten; dann stehen nur die eigenen Server da.
- **Sicherung vom anderen System:** Spielst du eine Sicherung vom Linux-PC unter Windows ein (oder umgekehrt), fragt PanePilot, ob nur die Einstellungen übernommen werden sollen – Symbolleiste, Tastenkürzel, Spalten, F-Tasten, Sprache usw. Favoriten, zuletzt offene Ordner, gespeicherte Abgleiche und Server bleiben dann, wie sie sind, weil deren Pfade auf dem anderen System nicht passen.
- **Attribute:** Statt Rechte, Besitzer und Gruppe gibt es die Spalte **Attribute** (R = schreibgeschützt, H = versteckt, S = System, A = Archiv) und in den Eigenschaften den Reiter **Attribute** zum Ändern.
- **Versteckte Dateien:** „Versteckte Dateien anzeigen“ zeigt Dateien mit dem Attribut „Versteckt“ und Namen mit Punkt am Anfang. Geschützte Systemdateien bleiben ausgeblendet, außer du schaltest sie in den Einstellungen ein.
- **Passwörter** (Server, OpenSubtitles, TMDb) liegen in der **Windows-Anmeldeinformationsverwaltung**.
- **Zwischenablage:** Zusätzlich Ordnerpfad, Dateipfad und Dateiname in Kurzform (8.3), Pfade „Web“ (mit `/`) und als UNC (`\\Rechner\Freigabe\…`).
- **Zusatzprogramme** (ffmpeg, exiftool, MKVToolNix, 7-Zip) installierst du selbst; welches wofür gebraucht wird und wie, steht unter [Zusatzprogramme](tools.md). Danach gehen die Video-Funktionen wie unter Linux.
- **Favoriten aus FreeCommander:** **Favoriten → Aus FreeCommander importieren …** öffnet den Einstellungsordner von FreeCommander mit der neuesten `FreeCommander.fav*.xml`. Daraus entsteht ein neuer Favoritensatz „FreeCommander“ (umbenennbar wie jeder Satz) mit den Kategorien als Favoritenordner, den Ordnern und Dateien und ihrer Schriftfarbe. Tastenkürzel, Sortierung und Ansicht aus FreeCommander entfallen.
- **„Danach“ beim Synchronisieren:** Herunterfahren und Energie sparen über Windows; Skripte `.bat`/`.cmd` laufen über cmd, `.ps1` über PowerShell, andere Befehle über cmd – mit denselben Umgebungsvariablen wie unter Linux (`%PANEPILOT_RESULT%` usw.).
