# Einstellungen

Die Einstellungen öffnet man über **Datei ▸ Einstellungen ▸ Einstellungen …** oder das Zahnrad. Links stehen die Bereiche des Reiters, rechts kann man durch alle Bereiche rollen. Das Mausrad verstellt dabei nichts aus Versehen – überall in PanePilot: Auswahllisten reagieren nur aufgeklappt aufs Rad, Regler und Zahlenfelder erst nach Anklicken. Steht der Mauszeiger in einer Liste oder Tabelle (z. B. „Vorhandene Sicherungen“), rollt nur diese, auch am Ende nicht weiter.

## Allgemein
- **Sprache**: Auswahl der Oberflächensprache, wirksam nach einem Neustart.
  - **Bearbeiten …** ändert Texte, auch bei Deutsch und den anderen mitgelieferten Sprachen. Gespeichert werden nur deine Änderungen.
  - Mit **Neue Sprache …** legt man eine eigene Sprache an.
  - **Exportieren …** und **Importieren …** tauschen Sprachdateien aus.
  - **Auf Original zurücksetzen** löscht deine Änderungen an einer mitgelieferten Sprache, **Sprache löschen** entfernt eine eigene Sprache.
- **Sicherung**: PanePilot sichert seine Einstellungen beim ersten Start jedes Tages. Hier stehen Ort, Anzahl und die Liste der Sicherungen mit Wiederherstellen, Importieren und Löschen.
- **Darstellung**: Knopfleiste, F-Tasten-Leiste, Symbolleiste, versteckte Dateien und Ein-Fenster-Ansicht.
  - **Skalierung** von 50 bis 200 %, z. B. für UHD-Bildschirme. Sie wird nach einem Neustart wirksam.
  - **Ins Anwendungsmenü aufnehmen** (nur beim Start als AppImage): legt einen Starter mit Programmsymbol an, den man auch ans Dock heften kann. Startet man später eine andere AppImage-Datei, zum Beispiel eine neuere Version, wird der Starter automatisch nachgeführt.
- **Erscheinungsbild**: **Wie das System** (Vorgabe – folgt der Hell/Dunkel-Einstellung von Windows bzw. Linux), **Hell** oder **Dunkel**; auf Linux und Windows gleich, die Markierung hat die Akzentfarbe des Systems. Im Dunkelmodus werden zu dunkle Favoritenfarben heller angezeigt. Einige Symbole passen sich erst nach einem Neustart an; PanePilot bietet ihn an.
  - **Schriftart** und **Größe** für die ganze Oberfläche, wirken sofort. **Standard** setzt beides zurück (Windows: Segoe UI 10 pt, Linux: Systemschrift).
- **Updates**: Unter **Automatisch nach Updates suchen** wählst du **Nie** (Vorgabe), **Einmal am Tag** (beim ersten Start des Tages) oder **Bei jedem Start**; PanePilot fragt dann bei GitHub nach einer neuen Version. Von Hand geht das jederzeit über **Hilfe ▸ Nach Updates suchen …**. Gibt es eine neue Version, kann man sie herunterladen, später erinnert werden oder diese Version überspringen. Beim Start als AppImage landet die neue Datei im selben Ordner wie die laufende; die alte bleibt erhalten. Danach fragt PanePilot, ob es gleich mit der neuen Version neu starten soll. Der Starter im Anwendungsmenü bzw. in der Taskleiste zeigt sofort auf die neue Datei – auch wenn du „Später“ wählst. Was mit der alten AppImage-Datei geschieht, legt **Alte AppImage-Datei nach einem Update** fest: **Nachfragen** (Vorgabe – beim ersten Start der neuen Version kommt einmal die Frage), **Immer in den Papierkorb** oder **Immer behalten**. Unter Windows lädt „Herunterladen“ beim installierten PanePilot das neue Setup in „Downloads“ und startet es auf Wunsch (PanePilot wird dafür beendet); bei der portablen Version wird das neue ZIP geladen. Ist PanePilot als Paket (.deb/.rpm) installiert, lädt „Herunterladen“ das neue Paket in den Ordner „Downloads“ und öffnet es mit der Software-Installation; der Knopf „Ins Anwendungsmenü aufnehmen“ fehlt dort, weil das Paket den Menüeintrag selbst mitbringt.
- **FTP-Server**: **Aus FileZilla importieren …** übernimmt die Serverliste von FileZilla, siehe [FTP-Server](servers.md).
- **Terminal**: welches Programm „Terminal hier öffnen“ startet. Linux: **Automatisch** (Standard-Terminal des Systems), GNOME Terminal, Konsole oder ein **eigener Befehl**. Windows: **Automatisch** (Windows Terminal, sonst PowerShell), Windows Terminal, PowerShell, Eingabeaufforderung (cmd) oder ein eigener Befehl. Im eigenen Befehl steht `{folder}` für den Ordner, z. B. `"C:\Program Files\Git\git-bash.exe" --cd={folder}`.

## Dateiansicht
- **Größeneinheit**: wie Dateigrößen angezeigt werden.
- **Systemdateien** (nur Windows): **Geschützte Systemdateien anzeigen** – Dateien mit den Attributen „Versteckt“ und „System“ (z. B. `NTUSER.DAT`, `pagefile.sys`) erscheinen nur damit, und nur, wenn versteckte Dateien angezeigt werden.
- **Netzwerk** (nur Windows): **Netzwerk im Ordnerbaum durchsuchen** – zeigt unter „Netzwerk“ die gefundenen Rechner; aus: nur die selbst eingetragenen Server.
- **Dateilisten**: **Abwechselnde Zeilenfarben** (Vorgabe aus) und **Rasterlinien zwischen den Spalten** (senkrechte Linien durch die ganze Liste, Vorgabe an).
- **Favoriten sortieren**: Reihenfolge für „Nach Name sortieren“ – **Ordner zuerst** (Vorgabe), **Favoriten zuerst** oder **Gemischt**.
- **Spalten**: Spaltenprofile mit sichtbaren Spalten und Ausrichtung, dazu das Standardprofil für das linke und das rechte Panel.

## Meta-Wizard
- **ReplayGain**: Ziel-Lautheit, Standard −18 LUFS.
- **Untertitel**: Zugang zu OpenSubtitles und was mit heruntergeladenen Untertiteln nach dem Einbinden geschieht: im Ordner belassen (Vorgabe), in den Papierkorb oder endgültig löschen.

## Zusatzprogramme
- Für ffmpeg/ffprobe, exiftool, MKVToolNix und 7-Zip: gefunden oder fehlt, eigener Pfad mit **Durchsuchen …** und Link zur Download-Seite. Welches Programm wofür gebraucht wird: [Zusatzprogramme](tools.md).

## Weitere Anpassungen direkt im Fenster
- **Symbolleiste**: Rechtsklick ▸ „Symbolleiste anpassen“, dort auch Abstände und „Ab hier rechtsbündig“.
- **F-Tasten**: Rechtsklick auf die F-Tasten-Leiste belegt die Tasten, in vier Schichten (ohne, Umschalt, Strg, Alt).
- **Tastenkürzel**: siehe [Tastenkürzel](shortcuts.md).

Alle Einstellungen liegen im Ordner `~/.config/PanePilot/`.
