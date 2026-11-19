# Ordner vergleichen und synchronisieren

## Ordner vergleichen
**Datei → Ordner vergleichen** (Strg+Umschalt+V) vergleicht den Ordner im linken mit dem im rechten Fenster und **markiert** in beiden Fenstern die Dateien, die nur auf dieser Seite liegen oder dort neuer sind. Mit Kopieren (F5) bringst du sie dann auf die andere Seite. Unterordner werden dabei nicht durchsucht – das macht „Ordner synchronisieren“.

Zwei Dateien gelten als **gleich**, wenn Name, Größe und Änderungsdatum übereinstimmen. Bis zu 2 Sekunden Abweichung zählen nicht (USB-Sticks und manche NAS speichern die Zeit ungenau). Die Einstellungen „1 Stunde Abweichung ignorieren“ und „Inhalt vergleichen“ aus dem Synchronisieren-Dialog gelten auch hier.

## Ordner synchronisieren
**Datei → Ordner synchronisieren …** (Strg+Umschalt+S) öffnet einen Dialog mit den Ordnern der beiden Fenster (änderbar, ⇅ tauscht die Seiten).

- **Richtung:** links → rechts, rechts → links oder beide Richtungen (die neuere Datei gewinnt). **Unterordner** sind standardmäßig dabei.
- **Spiegeln:** Mit „Überzählige im Ziel löschen“ sind danach beide Seiten gleich: Was nur im Ziel liegt, kommt in den **Papierkorb**, und neuere Dateien im Ziel werden überschrieben. Ohne Häkchen bleiben sie unberührt. Bei „beide Richtungen“ wird nichts gelöscht, sondern auf die andere Seite kopiert.
- **1 Stunde Abweichung ignorieren:** für Laufwerke, die Zeiten ohne Zeitzone speichern (nach der Zeitumstellung weichen sie genau eine Stunde ab).
- **Inhalt vergleichen:** Dateien mit gleicher Größe und gleichem Datum werden zusätzlich Byte für Byte verglichen (langsam).
- **Filter:** „Nur Dateien“ z. B. `*.jpg; *.png`, „Auslassen“ z. B. `Thumbs.db; .DS_Store; *.tmp` (gilt auch für Ordner).
- **Vergleichen** zeigt eine Liste aller Unterschiede mit Größe und Datum beider Seiten und der geplanten **Aktion**. Fett heißt: Hier passiert etwas. Mit „Gleiche Dateien anzeigen“ siehst du auch den Rest.
- **Aktion ändern:** Zeilen markieren (Strg/Umschalt, Strg+A für alle) und unten oder per Rechtsklick „→ nach rechts“, „← nach links“, „Rechts löschen“, „Links löschen“ oder „Nichts tun“ wählen. Was für eine Zeile nicht passt (z. B. „nach rechts“ bei einer Datei, die nur rechts liegt), bleibt, wie es ist.
- **Konflikt:** Haben beide Seiten dasselbe Datum, aber unterschiedlichen Inhalt bzw. Größe, lässt sich nicht sagen, welche stimmt. Solche Dateien stehen auf „nichts tun“ – du entscheidest.
- **Starten** fragt noch einmal nach und kopiert dann mit Fortschrittsanzeige (abbrechbar). Am Ende gibt es eine Zusammenfassung, danach wird neu verglichen.

## Gespeicherte Abgleiche
Mit **Speichern …** merkt sich PanePilot den Abgleich unter einem Namen (z. B. „Fotos → NAS“): beide Ordner, alle Einstellungen und die Aktion nach dem Beenden. Aufrufen über die Auswahl oben im Dialog oder über **Datei → Gespeicherte Abgleiche** – dann wird sofort verglichen; gestartet wird nach deiner Durchsicht mit „Starten“. Die Abgleiche sind in der Sicherung der Einstellungen enthalten.

## Nach dem Beenden
- **Befehl oder Skript ausführen:** läuft im Hintergrund ohne Terminal. Das Skript bekommt diese Umgebungsvariablen: `PANEPILOT_LEFT`, `PANEPILOT_RIGHT`, `PANEPILOT_RESULT` (`ok` oder `errors`), `PANEPILOT_COPIED`, `PANEPILOT_DELETED`, `PANEPILOT_FAILED`, `PANEPILOT_PROFILE`. Meldet das Skript einen Fehler (Rückgabewert ungleich 0), zeigt die Zusammenfassung das mit den letzten Zeilen seiner Ausgabe.
- **Rechner in Bereitschaft versetzen** bzw. **herunterfahren:** vorher läuft ein Countdown von 30 Sekunden mit „Abbrechen“.
- **Wann:** „nur wenn fehlerfrei“ (Vorgabe) oder „immer“. Nach einem Abbruch passiert nichts.

Server-Fenster (FTP/SFTP) lassen sich nicht synchronisieren; eingehängte NAS-Freigaben funktionieren wie lokale Ordner.
