# Meta wizard

**Meta wizard …** (Ctrl+T) edits the tags of music files (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV), similar to MP3TAG.

## Basics
- The track list shows the files of the current folder with their tags. Choose columns by right-clicking the column headers; you can also create your own fields there.
- You edit the selected tracks in the sidebar. With several tracks that have different values it shows `< keep >`: whatever you don’t touch stays as it is in each file.
- Changes are only **pending** at first and marked green. **Save tag** writes them to the files. **Undo** reverts the last save.
- **Cover**: drag an image in, or right-click the cover to load, save or remove it.

## Converters
- **File name → tag**, **tag → file name**, **tag → tag**: with format strings like `%track% - %title%`, with a preview and templates.
- **Tag → text file/CSV** and **text file → tag**: for editing in LibreOffice or for taking over a track list from the internet. In the assignment window, placeholders make up for missing lines.
- **Number …**: track numbers from top to bottom, optionally with the total (e.g. “01/12”).
- **Create playlist …**: M3U8 playlist with relative or absolute paths.
- **ReplayGain …**: measures the loudness with ffmpeg (EBU R128) and adds track and album values. The target loudness is in the [Settings](settings.md). This requires ffmpeg to be installed.

The meta wizard closes with its “Close” button or when you call it again. Pending changes are only lost after a confirmation.
