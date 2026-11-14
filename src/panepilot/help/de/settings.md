# Einstellungen

Die Einstellungen öffnet man über **Datei ▸ Einstellungen ▸ Einstellungen …** oder das Zahnrad. Links stehen die Bereiche des Reiters, rechts kann man durch alle Bereiche rollen.

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
- **Updates**: Ist **Einmal täglich beim Start nach Updates suchen** eingeschaltet (Vorgabe: aus), fragt PanePilot beim ersten Start des Tages bei GitHub nach einer neuen Version. Von Hand geht das jederzeit über **Hilfe ▸ Nach Updates suchen …**. Gibt es eine neue Version, kann man sie herunterladen, später erinnert werden oder diese Version überspringen. Beim Start als AppImage landet die neue Datei im selben Ordner wie die laufende; die alte bleibt erhalten. Danach fragt PanePilot, ob es gleich mit der neuen Version neu starten soll.

## Dateiansicht
- **Größeneinheit**: wie Dateigrößen angezeigt werden.
- **Spalten**: Spaltenprofile mit sichtbaren Spalten und Ausrichtung, dazu das Standardprofil für das linke und das rechte Panel.

## Meta-Wizard
- **ReplayGain**: Ziel-Lautheit, Standard −18 LUFS.

## Weitere Anpassungen direkt im Fenster
- **Symbolleiste**: Rechtsklick ▸ „Symbolleiste anpassen“, dort auch Abstände und „Ab hier rechtsbündig“.
- **F-Tasten**: Rechtsklick auf die F-Tasten-Leiste belegt die Tasten, in vier Schichten (ohne, Umschalt, Strg, Alt).
- **Tastenkürzel**: siehe [Tastenkürzel](shortcuts.md).

Alle Einstellungen liegen im Ordner `~/.config/PanePilot/`.
