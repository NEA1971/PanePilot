# Zusatzprogramme

Einige Funktionen nutzen Programme, die PanePilot nicht mitbringt, weil sie das Programm stark vergrößern würden. PanePilot erkennt beim Start der jeweiligen Funktion, ob sie installiert sind. Fehlt eins, fehlt nur die zugehörige Funktion; ein Hinweis nennt das fehlende Programm.

| Programm | Wofür PanePilot es braucht | Was ohne es fehlt |
|---|---|---|
| **ffmpeg** (mit ffprobe) | ReplayGain messen; Dauer, Auflösung, Codecs, Aufnahmedatum und GPS von Videos lesen; Standbild als Vorschau; Spuren in MP4 entfernen, Spurnamen/„Standard“ ändern; MKV → MP4; unvollständige MKV-Dateien reparieren; Duplikatsuche bei Videos | ReplayGain ist grau; bei Videos fehlen diese Angaben, MKV/AVI/MTS zeigen fast nichts; die genannten Video-Funktionen |
| **exiftool** | HEIC-Fotos schreiben; Aufnahmedatum und GPS von MP4/MOV-Videos ändern bzw. entfernen | HEIC-Fotos nur lesen; bei MP4/MOV sind Aufnahmedatum und GPS grau |
| **MKVToolNix** (mkvmerge, mkvextract, mkvpropedit) | MKV- und WebM-Videos beschriften; Spuren und Untertitel in MKV entfernen, umsortieren, einbinden; MP4/AVI/MOV → MKV; Kapitel in MKV | MKV/WebM nur lesen; diese Spur-Funktionen |
| **7-Zip** (7z) | Archive im 7z-Format und weitere Formate packen, entpacken und beschreiben; verschlüsselte ZIPs; RAR lesen | diese Archivformate |
| **rar / unrar** (nur Linux) | RAR-Archive entpacken (rar auch packen) | RAR-Archive (unter Windows liest 7-Zip RAR) |

## Installieren unter Linux (Debian/Ubuntu)
Im Terminal: `sudo apt install ffmpeg libimage-exiftool-perl mkvtoolnix 7zip unrar`.

## Installieren unter Windows
- **ffmpeg:** in der Eingabeaufforderung `winget install Gyan.FFmpeg` – oder das ZIP von ffmpeg.org nach `C:\ffmpeg` entpacken (die Programme liegen dann in `C:\ffmpeg\bin`).
- **exiftool:** das Windows-Paket von exiftool.org installieren (landet in `C:\Program Files\ExifTool`) oder `winget install OliverBetz.ExifTool`.
- **MKVToolNix:** Setup von mkvtoolnix.download (landet in `C:\Program Files\MKVToolNix`).
- **7-Zip:** Setup von 7-zip.org (landet in `C:\Program Files\7-Zip`).

PanePilot sucht zuerst im Suchpfad (PATH), dann in diesen üblichen Ordnern (auch winget, Scoop und Chocolatey).

## Einstellungen → Zusatzprogramme
Hier steht für jedes Programm, ob es gefunden wurde (Maus über „gefunden“ zeigt den Pfad), mit Link zur Download-Seite. Liegt ein Programm woanders, trägst du den Pfad ein oder wählst ihn mit **Durchsuchen …**; ein eigener Pfad geht vor.

Nach dem Installieren genügt es, den Meta-Wizard bzw. die Funktion neu zu öffnen; ein Neustart von PanePilot ist nicht nötig. Ob ffmpeg gefunden wurde, steht auch unter **Hilfe → Über PanePilot**.
