# PanePilot

**A free two-panel file manager for Linux, inspired by FreeCommander.**

PanePilot brings together what usually takes three or four programs: a classic two-panel file manager, a powerful multi-rename tool, a music tag editor in the style of MP3TAG, and a checksum tool – in one fast, keyboard-friendly application.

![PanePilot main window](docs/screenshots/main.png)

[**⬇ Download the latest release**](https://github.com/NEA1971/PanePilot/releases/latest) · [Report a bug / suggest a feature](https://github.com/NEA1971/PanePilot/issues/new/choose) · [Discussions](https://github.com/NEA1971/PanePilot/discussions) · [☕ Support on Ko-fi](https://ko-fi.com/panepilot)

🇩🇪 [Deutsche Beschreibung weiter unten](#deutsch)

## Features

- **Two panels** with folder tree, nested favourites, drive overview (including network shares and USB drives that are not mounted yet), filters, column profiles and a single-panel view
- **File operations**: copy, move, rename, trash, archives (compress / extract), drag & drop to and from other applications, “Open with”, properties, “Open terminal here”, directory listings as text file
- **Search** by name (wildcards, several patterns) and by content, with depth limit; results appear as a normal panel
- **Multi-rename** with placeholders, counters, dates, search & replace (text, wildcards, regular expressions), live preview, profiles and undo
- **Meta wizard** for music tags (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV):
  - edit tags and covers for many files at once
  - converters: file name ↔ tag, tag → tag, text/CSV export and import, track numbering
  - M3U8 playlists
  - **ReplayGain** (EBU R128, via ffmpeg)
- **Checksums**: CRC32, MD5, SHA-1, SHA-256, SHA-512, with comparison and drag & drop of checksum files (`SHA256SUMS`, `.md5`, SFV …)
- **Fully configurable**: keyboard shortcuts, function-key bar (four layers), toolbar, sidebars
- **Six languages**: English, German, Spanish, French, Russian and Franconian. You can edit any language or add your own.
- **Built-in help** (F1 opens the page for the current function) and automatic daily backup of all settings
- **UI scaling** (50–200 %) for high-resolution screens, optional entry in the application menu

| Meta wizard | Multi-rename |
|---|---|
| ![Meta wizard](docs/screenshots/metawizard.png) | ![Multi-rename](docs/screenshots/multirename.png) |

## Installation

PanePilot is distributed as an **AppImage** for 64-bit Linux (x86_64). Nothing needs to be installed:

1. Download `PanePilot-x.y.z-x86_64.AppImage` from the [latest release](https://github.com/NEA1971/PanePilot/releases/latest).
2. Make it executable: right-click → Properties → “Executable as program”, or `chmod +x PanePilot-*.AppImage`.
3. Double-click to start.
4. Optional: *Settings ▸ General ▸ Display ▸ Add to application menu* creates a launcher with icon.

PanePilot supports [AppImageUpdate](https://github.com/AppImageCommunity/AppImageUpdate) and Gear Lever for delta updates.

Optional: install `ffmpeg` (e.g. `sudo apt install ffmpeg`) to use ReplayGain.

Settings are stored in `~/.config/PanePilot/`.

## Feedback

- Found a bug or have an idea? Please open an [issue](https://github.com/NEA1971/PanePilot/issues/new/choose). The **System** tab in *Help ▸ About PanePilot* has a **Copy** button for the technical details.
- Questions and general discussion: [Discussions](https://github.com/NEA1971/PanePilot/discussions).

## Support

PanePilot is free and will stay free. If you like it, you can support its development with a coffee on [**Ko-fi**](https://ko-fi.com/panepilot). Supporters receive a personal code that removes the friendly reminder in the app.

## Building from source

```bash
pip install -r requirements-dev.txt
PYTHONPATH=src python -m panepilot      # run
QT_QPA_PLATFORM=offscreen pytest        # tests
packaging/build_appimage.sh             # build the AppImage (see the release workflow)
```

Python 3 (tested with 3.12) and Qt 6 (PySide6). Releases are built by GitHub Actions: bump the version in `src/panepilot/__init__.py`, add `docs/releases/vX.Y.Z.md` and push to `main`.

## License

PanePilot is free software, licensed under the [GNU General Public License v3.0 or later](LICENSE).
© 2026 NEA1971

---

<a id="deutsch"></a>
## 🇩🇪 Deutsch

**PanePilot ist ein kostenloser Zwei-Fenster-Dateimanager für Linux nach dem Vorbild von FreeCommander.**

Er vereint, wofür man sonst drei oder vier Programme braucht:
- Dateimanager mit zwei Fenstern, Ordnerbaum, Favoriten und Laufwerken
- Suche nach Namen und Inhalt
- Mehrfach-Umbenennen mit Vorschau
- **Meta-Wizard** für Musik-Tags wie MP3TAG, mit ReplayGain und Playlists
- **Prüfsummen** zum Vergleichen von Downloads

Die Oberfläche gibt es komplett auf Deutsch, die Hilfe mit F1 ebenfalls.

**Installation:**
1. Das AppImage unter [Releases](https://github.com/NEA1971/PanePilot/releases/latest) herunterladen.
2. Ausführbar machen: Rechtsklick → Eigenschaften → „Als Programm ausführbar“.
3. Per Doppelklick starten.

**Rückmeldungen:** Fehler und Wünsche gern als [Issue](https://github.com/NEA1971/PanePilot/issues/new/choose), auch auf Deutsch. Fragen in den [Discussions](https://github.com/NEA1971/PanePilot/discussions).

**Unterstützen:** PanePilot ist und bleibt kostenlos. Wer die Weiterentwicklung unterstützen möchte, kann das über [Ko-fi](https://ko-fi.com/panepilot) tun.
