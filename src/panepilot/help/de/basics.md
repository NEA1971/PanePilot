# Bedienung

PanePilot zeigt zwei Dateifenster (Panels) nebeneinander. Eines davon ist **aktiv**, erkennbar an der farbigen Pfadzeile. Die meisten Befehle gelten für die markierten Einträge im aktiven Panel. Kopieren und Verschieben gehen immer **ins andere Panel**.

## Navigieren
- **Doppelklick** oder **Enter** öffnet einen Ordner bzw. öffnet eine Datei mit ihrem Standardprogramm.
- **Rücktaste** geht eine Ebene höher. Die Maustasten „Zurück“ und „Vor“ funktionieren wie im Browser.
- **Tab** wechselt zwischen den Panels.
- In die **Pfadzeile** kann man einen Pfad direkt eintippen.
- Im Menü **Navigation**: gleicher Ordner im anderen Panel, Panels tauschen, Zurück, Vor.
- **Zuletzt besuchte Ordner**: der Pfeil rechts in der Pfadzeile (oder Alt+↓) zeigt die letzten 20 Ordner beider Fenster, neueste oben; die Liste wird beim Beenden gemerkt.

## Reiter
- Jedes Fenster kann mehrere **Reiter** haben: **Strg+T** öffnet einen neuen Reiter mit dem aktuellen Ordner, **Strg+W** schließt ihn, **Strg+Tab** / **Strg+Umschalt+Tab** wechseln.
- Neuer Reiter auch mit der **mittleren Maustaste** oder **Strg+Doppelklick** auf einen Ordner und per Doppelklick auf die freie Reiterleiste. Die mittlere Maustaste auf einem Reiter schließt ihn; Reiter lassen sich per Ziehen umsortieren.
- Jeder Reiter hat seinen eigenen Ordner, Verlauf, Sortierung, Filter und Ansicht (Details/Symbole); Spalten und Seitenleiste gelten für das ganze Fenster.
- **Rechtsklick auf einen Reiter**: Neuer Reiter, Schließen, Andere schließen, Sperren/Entsperren, Im anderen Fenster öffnen. Ein **gesperrter Reiter** (🔒) bleibt stehen – wechselt man darin den Ordner, öffnet sich ein neuer Reiter.
- Die Reiterleiste erscheint ab dem zweiten Reiter (Einstellungen → Dateiansicht → Reiter: „immer anzeigen“). Während Suche, Umbenennen, Meta-Wizard, Synchronisieren oder einer Server-Verbindung sind die Reiter dieses Fensters gesperrt. Alle Reiter werden beim Beenden gemerkt.

## Dateien bearbeiten
- **Kopieren / Verschieben** ins andere Panel (F5 / F6) fragt vorher nach, die Varianten „ohne Rückfrage“ legen sofort los. Ziehen mit der Maus geht ebenfalls, auch von und nach Nautilus.
- **Umbenennen** (F2), **Neuer Ordner** (F7), **Neue Textdatei** (Umschalt+F4), **In den Papierkorb** (F8), **Endgültig löschen**. Beim Umbenennen zeigt das Eingabefeld immer den kompletten Namen mit Endung – auch in der Spalte „Name (ohne Endung)“. Vorab markiert ist der Teil vor der Endung; die Endung lässt sich mit ändern.
- **Zwischenablage**: Kopieren, Ausschneiden, Einfügen (Strg+C/X/V), auch zusammen mit anderen Programmen.
- **Pfade und Namen in die Zwischenablage** (Menü Bearbeiten, Rechtsklick → „In die Zwischenablage“ oder Pfeil am Knopf „Kopieren“): Dateipfad (Alt+Einfg), Dateiname (Alt+Umschalt+Einfg), Dateiname ohne Erweiterung, Ordnerpfad, Dateipfad als Adresse (`file:///…`) und Details (Name, Größe in Bytes, Datum, Typ – durch Tabulator getrennt, z. B. zum Einfügen in Excel). Bei mehreren markierten Dateien steht jede in einer eigenen Zeile.
- **Duplizieren** (Strg+D, auch im Rechtsklick-Menü): legt von den markierten Dateien und Ordnern im selben Ordner eine Kopie an, ohne Rückfrage – `Bericht.docx` wird zu `Bericht-Kopie.docx`, beim nächsten Mal `Bericht-Kopie-2.docx`. Die Kopien sind danach markiert, z. B. zum Umbenennen mit F2. Auf FTP-/SFTP-Servern nicht möglich.
- **Fenster übereinander** (Ansicht → „Fenster übereinander“, Strg+Umschalt+H): stellt die beiden Fenster übereinander statt nebeneinander. Jedes Fenster behält seine Seitenleiste links daneben, die Knopfleiste liegt waagerecht dazwischen. Die Aufteilung wird für beide Anordnungen getrennt gemerkt.
- **Aktualisieren** (Strg+R, auch ganz unten im Rechtsklick-Menü): liest den angezeigten Ordner neu ein; die Markierung bleibt erhalten.
- **Öffnen mit**: Rechtsklick auf eine Datei zeigt die passenden Programme, „Andere Anwendung …“ alle.
- **Archive**: Komprimieren und Entpacken über das Rechtsklick-Menü.
- **Eigenschaften** (Alt+Enter) zeigt Größe, Rechte, Daten und bei Musik, Fotos, Videos und Dokumenten die Metadaten.
- **Terminal hier öffnen** (Menü Datei oder Rechtsklick): öffnet das Standard-Terminal im angezeigten Ordner, nach Rechtsklick auf einen Ordner in diesem.
- **Verzeichnisliste erstellen …** (Menü Datei oder Rechtsklick): schreibt eine eingerückte Liste des Ordners mit Größen und Änderungsdatum in eine Textdatei. Man wählt Tiefe, ob Dateien und versteckte Einträge dazugehören und ob die Liste danach geöffnet wird.

## Ansicht
- **Filter** (Menü Ansicht): zeigt nur passende Einträge, z. B. `*.mp3`. Mehrere Muster trennt man mit Semikolon oder Komma, z. B. `*.mkv;*.mp4`. Ein aktiver Filter färbt die Pfadzeile rot.
- **Versteckte Dateien**, **Ein-Fenster-Ansicht**, Knopfleiste, F-Tasten-Leiste und Symbolleiste lassen sich im Menü **Ansicht** ein- und ausschalten.
- Spalten: Rechtsklick auf die Spaltenköpfe. Reihenfolge und Breite stellt man direkt durch Ziehen ein (siehe [Einstellungen](settings.md)).

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
