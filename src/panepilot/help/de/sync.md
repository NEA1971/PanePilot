# Ordner vergleichen und synchronisieren

## Ordner vergleichen
**Datei → Ordner vergleichen** (Strg+Umschalt+V) vergleicht den Ordner im linken mit dem im rechten Fenster und **markiert** in beiden Fenstern die Dateien, die nur auf dieser Seite liegen oder dort neuer sind. Mit Kopieren (F5) bringst du sie dann auf die andere Seite. Unterordner werden dabei nicht durchsucht – das macht „Ordner synchronisieren“.

Zwei Dateien gelten als **gleich**, wenn Name, Größe und Änderungsdatum übereinstimmen. Bis zu 2 Sekunden Abweichung zählen nicht (USB-Sticks und manche NAS speichern die Zeit ungenau). Die Einstellungen „1 Stunde Abweichung ignorieren“ und „Inhalt vergleichen“ aus der Seitenleiste „Synchronisieren“ gelten auch hier.

## Ordner synchronisieren
**Datei → Ordner synchronisieren …** (Strg+Umschalt+S) schaltet das Hauptfenster in die **Vergleichsansicht**: links die Seitenleiste „Synchronisieren“ mit allen Einstellungen, daneben die beiden Ordner wie zwei Explorer-Fenster (die Pfade oben sind änderbar, ⇄ tauscht die Seiten). Mit dem ✕ bzw. „Schließen“ in der Seitenleiste oder Esc geht es zurück zur normalen Ansicht.

- **Richtung:** links → rechts, rechts → links oder beide Richtungen (die neuere Datei gewinnt). **Unterordner** sind standardmäßig dabei.
- **Spiegeln: Ziel wird genau wie die Quelle:** Danach sind beide Seiten gleich: Was nur im Ziel liegt, kommt in den **Papierkorb**, und neuere Dateien im Ziel werden überschrieben. Ohne Häkchen bleiben sie unberührt. Bei „beide Richtungen“ wird nichts gelöscht, sondern auf die andere Seite kopiert.
- **1 Stunde Abweichung ignorieren:** für Laufwerke, die Zeiten ohne Zeitzone speichern (nach der Zeitumstellung weichen sie genau eine Stunde ab).
- **Inhalt vergleichen:** Dateien mit gleicher Größe und gleichem Datum werden zusätzlich Byte für Byte verglichen (langsam).
- **Filter:** „Einschließen (nur Dateien)“ z. B. `*.jpg; *.png` – Ordner werden dabei immer durchsucht; „Ausschließen (Dateien und Ordner)“ z. B. `Thumbs.db; .DS_Store; *.tmp; backup` – ein ausgeschlossener Ordner fällt samt Inhalt weg, der Name gilt in jeder Tiefe. Per Rechtsklick auf einen Ordner trägt **„Ordner … ausschließen“** ihn hier ein und vergleicht neu (zum Merken den Abgleich speichern).
- **Vergleichen** zeigt die Unterschiede als **Baum**: links und rechts jeweils Name, Größe und Datum, die Zeilen beider Seiten auf gleicher Höhe (fehlt eine Datei auf einer Seite, bleibt die Zeile dort leer). Ordner lassen sich mit **+** / **−** auf- und zuklappen; nach dem Vergleichen ist alles zugeklappt (nur die oberste Ebene); ein Doppelklick auf einen Ordner klappt ihn ebenfalls auf und zu. Ordner ohne Unterschiede sind ausgeblendet, mit „Gleiche Dateien anzeigen“ siehst du auch den Rest.
- In der **Mittelspalte** steht je Zeile das Symbol der geplanten Aktion: → bzw. ← kopieren oder überschreiben, ✕ löschen, ! Konflikt, – nichts tun; ein Ordner zeigt die Aktion seines Inhalts, • heißt „unterschiedlich“. Der Text steht im Tooltip.
- **Aktion ändern:** Zeilen markieren (Strg/Umschalt, Strg+A für alle) und mit den Knöpfen unter der Mittelspalte (→ ← ✕▸ ◂✕ –) oder per Rechtsklick festlegen. Für einen Ordner gilt die Aktion für alles darin; einzelne Einträge kannst du danach umstellen. Was für eine Zeile nicht passt (z. B. „nach rechts“ bei einer Datei, die nur rechts liegt), bleibt, wie es ist.
- **Doppelklick** auf eine Datei, die auf beiden Seiten vorhanden ist und abweicht, öffnet **Dateien vergleichen**; sonst öffnet er die Datei der angeklickten Seite mit dem Standardprogramm.
- **Funktionstasten** in der Vergleichsansicht: F1 Hilfe, F5 Synchronisieren, F8 markierte Zeilen rechts löschen.
- **Konflikt:** Haben beide Seiten dasselbe Datum, aber unterschiedlichen Inhalt bzw. Größe, lässt sich nicht sagen, welche stimmt. Solche Dateien stehen auf „nichts tun“ – du entscheidest.
- **Synchronisieren** (Knopf, F5 oder Rechtsklick in den leeren Bereich der Liste, dort auch „Vergleichen“) fragt noch einmal nach und kopiert dann mit Fortschrittsanzeige (abbrechbar). Am Ende gibt es eine Zusammenfassung, danach wird neu verglichen.

## Gespeicherte Abgleiche
In der Seitenleiste merkt sich PanePilot mit **Speichern …** den Abgleich unter einem Namen (z. B. „Fotos → NAS“): beide Ordner, alle Einstellungen und die Aktion nach dem Beenden. Aufrufen über die Auswahl oben in der Seitenleiste oder über **Datei → Gespeicherte Abgleiche** – dann wird sofort verglichen; synchronisiert wird nach deiner Durchsicht mit „Synchronisieren“. Die Abgleiche sind in der Sicherung der Einstellungen enthalten.

Unter der Auswahl steht der **letzte Lauf** des gewählten Abgleichs: grüner Haken = fehlerfrei, Verbotsschild = mit Fehlern oder abgebrochen. Der Infotext zeigt Datum, Zahlen und bei Fehlern die ersten Meldungen. Dasselbe steht im Menü **Datei → Gespeicherte Abgleiche** hinter dem Namen.

## FreeFileSync
- **FreeFileSync → Aus FreeFileSync importieren …** übernimmt `.ffs_gui`- und `.ffs_batch`-Dateien (mehrere auf einmal) als gespeicherte Abgleiche; der Name ist der Dateiname. Gibt es ihn schon, fragt PanePilot nach.
- Übernommen werden Ordnerpaar (bei mehreren je Paar ein Abgleich), Richtung, Spiegeln, Vergleich nach Inhalt, Filter und der Befehl nach dem Abgleich. „Aktualisieren“ wird zu „links → rechts“ ohne Spiegeln, „Spiegeln“ zu „links → rechts“ mit „Spiegeln: Ziel wird genau wie die Quelle“, echte Zwei-Wege-Abgleiche zu „beide Richtungen“.
- Die FFS-Datenbank `*.ffs_db` kommt automatisch unter „Ausschließen“. Was sich nicht übernehmen lässt (z. B. Versionierung, Größen- und Zeitfilter, Pfade in Filtern, Änderungserkennung per FFS-Datenbank), steht im Bericht nach dem Import.
- **Nach FreeFileSync exportieren …** speichert den eingestellten Abgleich als `.ffs_gui`, **Alle exportieren …** alle gespeicherten in einen Ordner. „1 Stunde ignorieren“ steht nicht in der Datei und muss bei Bedarf in FreeFileSync nachgetragen werden.

## Nach dem Beenden
- **Befehl oder Skript ausführen:** läuft im Hintergrund ohne Terminal. Das Skript bekommt diese Umgebungsvariablen: `PANEPILOT_LEFT`, `PANEPILOT_RIGHT`, `PANEPILOT_RESULT` (`ok` oder `errors`), `PANEPILOT_COPIED`, `PANEPILOT_DELETED`, `PANEPILOT_FAILED`, `PANEPILOT_PROFILE`. Meldet das Skript einen Fehler (Rückgabewert ungleich 0), zeigt die Zusammenfassung das mit den letzten Zeilen seiner Ausgabe.
- **Rechner in Bereitschaft versetzen** bzw. **herunterfahren:** vorher läuft ein Countdown von 30 Sekunden mit „Abbrechen“.
- **Wann:** „nur wenn fehlerfrei“ (Vorgabe) oder „immer“. Nach einem Abbruch passiert nichts.

Server-Fenster (FTP/SFTP) lassen sich nicht synchronisieren; eingehängte NAS-Freigaben funktionieren wie lokale Ordner.
