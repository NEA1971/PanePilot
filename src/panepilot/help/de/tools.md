# Zusatzprogramme

Einige Funktionen nutzen Programme, die nicht im AppImage enthalten sind, weil sie die Datei stark vergrößern würden. PanePilot erkennt beim Start der jeweiligen Funktion, ob sie installiert sind. Fehlt eins, fehlt nur die zugehörige Funktion; ein Hinweis nennt dann den Befehl. Unter Debian und Ubuntu installiert man sie im Terminal mit `sudo apt install …`.

| Programm | Wofür PanePilot es braucht | Was ohne es fehlt | Installieren |
|---|---|---|---|
| **ffmpeg** | ReplayGain messen; Dauer, Auflösung, Codecs, Aufnahmedatum und GPS von Videos lesen; Standbild als Vorschau | ReplayGain ist grau; bei Videos fehlen diese Angaben, MKV/AVI/MTS zeigen fast nichts | `sudo apt install ffmpeg` |
| **exiftool** | HEIC-Fotos schreiben; Aufnahmedatum und GPS von MP4/MOV-Videos ändern bzw. entfernen | HEIC-Fotos nur lesen; bei MP4/MOV sind Aufnahmedatum und GPS grau | `sudo apt install libimage-exiftool-perl` |
| **mkvpropedit, mkvextract** (Paket mkvtoolnix) | MKV- und WebM-Videos beschriften | MKV/WebM nur lesen | `sudo apt install mkvtoolnix` |
| **7-Zip** (7z) | Archive im 7z-Format und weitere Formate packen und entpacken | diese Archivformate | `sudo apt install 7zip` |
| **rar / unrar** | RAR-Archive entpacken (rar auch packen) | RAR-Archive | `sudo apt install unrar` bzw. `rar` |

Nach dem Installieren genügt es, den Meta-Wizard bzw. die Funktion neu zu öffnen; ein Neustart von PanePilot ist nicht nötig. Ob ffmpeg gefunden wurde, steht auch unter **Hilfe → Über PanePilot**.
