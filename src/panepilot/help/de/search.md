# Suchen

**Suchen …** (Strg+F) sucht ab dem Ordner des aktiven Panels.

- **Dateiname**: mit Platzhaltern wie `*.pdf` oder `urlaub*`. Mehrere Muster werden mit Semikolon getrennt.
- **Enthaltener Text**: durchsucht nur Textdateien, keine Bilder, Programme, Office- oder PDF-Dateien. Dateien über 100 MB werden übersprungen und gemeldet.
- **Suchtiefe**: nur dieser Ordner, eine bestimmte Zahl von Ebenen oder unbegrenzt.
- **Optionen**: versteckte Dateien durchsuchen, Ordner als Treffer anzeigen, Netzwerkfreigaben einbeziehen.

Die Treffer erscheinen im Panel wie ein normaler Ordner. Dort lässt sich alles damit machen: kopieren, löschen, umbenennen, öffnen. **Zum Ordner springen** öffnet den Ordner eines Treffers. Mit **Stopp** bricht man eine lange Suche ab.

## Duplikate suchen
**Datei → Duplikate suchen …** (oder Rechtsklick auf einen Ordner) öffnet ein eigenes Fenster. PanePilot bleibt währenddessen bedienbar.
- **Was gilt als doppelt:**
  - **a) Gleicher Inhalt** – byte-genau gleiche Dateien, auch mit verschiedenen Namen. PanePilot vergleicht erst die Größe und liest nur gleich große Dateien (Prüfsumme SHA-256). Leere Dateien zählen nicht.
  - **b) Gleicher Name ohne Endung** – z. B. `Alien (1979).mkv` und `Alien (1979).mp4`. Der Inhalt wird nicht verglichen. `Alien (1979).eng.srt` zählt nicht dazu, weil sein Name ohne Endung „Alien (1979).eng“ lautet.
  - **c) Gleicher Name und gleiche Größe** – schnell, ohne Prüfsumme.
  - b) und c) sind schnell. a) ist am genauesten, kann bei großen Dateien oder über das Netzwerk (NAS) aber lange dauern; die Fortschrittsanzeige zeigt, wie viel schon gelesen ist, **Abbrechen** beendet die Suche sofort.
- **Wo:** Startordner (änderbar), **Tiefe** 1 (nur dieser Ordner) bis 10 Ebenen oder unbegrenzt, wahlweise **auch der Ordner des anderen Fensters** – z. B. um eine Sicherung mit dem Original zu vergleichen.
- **Filter:** nur bestimmte Dateien wie `*.mp4;*.mkv` und eine **Mindestgröße** in MB. Versteckte Dateien werden nur berücksichtigt, wenn das Dateifenster sie anzeigt; Verknüpfungen werden nicht verfolgt.
- **Ergebnis:** eine Gruppe je Duplikat mit Name, Ordner, Größe und Änderungsdatum, darüber die Zusammenfassung (Gruppen, Dateien, überzählige Dateien und deren Größe).
- **Ankreuzen:** einzeln oder mit **Ankreuzen → alle außer der neuesten / ältesten / größten** bzw. **nichts ankreuzen**.
- **In den Papierkorb** verschiebt die angekreuzten Dateien nach einer Rückfrage. Sind in einer Gruppe alle Dateien angekreuzt, warnt PanePilot ausdrücklich. Endgültiges Löschen gibt es hier bewusst nicht.
- **Im Dateifenster zeigen** (oder Doppelklick) springt im aktiven Fenster zur Datei, **Liste speichern …** legt die Gruppen als Textdatei ab.
- PanePilot merkt sich die zuletzt gewählten Einstellungen und die Fenstergröße.
