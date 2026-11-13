# Meta wizard

**Meta wizard …** (Ctrl+T) edits the tags of music files (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV), similar to MP3TAG, and the metadata of photos (see below).

## Basics
- The track list shows the files of the current folder with their tags. Choose columns by right-clicking the column headers; you can also create your own fields there.
- You edit the selected tracks in the sidebar. With several tracks that have different values it shows `< keep >`: whatever you don’t touch stays as it is in each file.
- Changes are only **pending** at first and marked green. **Save tag** writes them to the files. **Undo** reverts the last save.
- **Cover**: drag an image in, or right-click the cover to load, save or remove it.

## Converters
- **File name → tag**, **tag → file name**, **tag → tag**: with format strings like `%track% - %title%`, with a preview and templates.
- **Tag → text file/CSV** and **text file → tag**: for editing in LibreOffice or for taking over a track list from the internet. In the assignment window, placeholders make up for missing lines.
- **Number …**: track numbers from top to bottom, optionally with the total (e.g. “01/12”).
- **Disc numbers …**: assigns disc numbers for multi-disc albums – by subfolder (e.g. CD1, CD2), anew whenever the track number starts again, or manually. The total number of discs can go into the disc field as “1/2” or into a separate DISCTOTAL field.
- **MusicBrainz …**: looks up the album in the free music database [MusicBrainz](https://musicbrainz.org) (requires an internet connection).
  1. Album and artist are prefilled from the tags and can be changed.
  2. The result list can be sorted by any column. Releases with as many tracks as files are selected are marked green.
  3. The apply window shows the track and album fields with checkboxes at the top – only checked fields are applied; double-click a value to change it – and the cover (from the Cover Art Archive, at most 1200 × 1200 pixels). At the bottom you assign the MusicBrainz tracks to the files, just like in “text file → tag”. Yellow means the length differs by more than 5 seconds.
  4. **OK** marks the values green as pending, **Save tag** writes them. The year is the year of the first release. The MusicBrainz identifiers are stored the same way as MusicBrainz Picard does.
- **Create playlist …**: M3U8 playlist with relative or absolute paths.
- **ReplayGain …**: measures the loudness with ffmpeg (EBU R128) and adds track and album values. The target loudness is in the [Settings](settings.md). This requires ffmpeg to be installed.

The meta wizard closes with its “Close” button or when you call it again. Pending changes are only lost after a confirmation.

## Photos
If the folder contains photos, the meta wizard shows their metadata (EXIF, IPTC, XMP). If music and photos are mixed, choose what to show with **“Music | Photos”** at the top; the kind with more files is preselected.
- **Read and write**: JPEG, PNG, TIFF, WebP. **HEIC/HEIF** (phone photos) only if the **exiftool** program is installed (`sudo apt install libimage-exiftool-perl`), otherwise read-only. **RAW** files (CR2, NEF, ARW, DNG …) are read-only.
- **Edit**: title, description, keywords (separated by “;”), rating (0–5), author, copyright and date taken. PanePilot writes each field to all the usual places (XMP, IPTC, EXIF) so that e.g. digiKam or the image viewer finds it.
- **Camera, lens, exposure, aperture, ISO, focal length, flash, orientation and GPS** cannot be changed but can be removed with `< remove >` – e.g. the GPS position before sharing photos. **Show on map** opens the position in OpenStreetMap.
- **Custom fields** are added via the column headers as for music. They are stored as XMP; other programs usually read them but do not show them in their normal view – for things that should be visible everywhere, keywords are the better place.
- Instead of the cover, the sidebar shows a **preview**.
- **Converters** for photos: tag → file name, file name → tag, tag → tag, tag → text file/CSV, text file → tag and **Shift date …**.
  - Placeholders: `%datetaken%`, `%make%`, `%model%`, `%lens%`, `%iso%`, `%title%`, `%rating%`, `%author%` …, plus `%camera%`, `%width%`, `%height%`.
  - `$date(%datetaken%,JJJJ-MM-TT_hhmmss)` reformats the date, e.g. to `2026-11-08_150012` (JJJJ = year, MM = month, TT = day, hh/mm/ss = time). Without a date taken, the file’s modification date is used.
  - **Shift date …** moves the date taken by days, hours, minutes and seconds, e.g. if the camera clock was wrong. Photos without a date taken are skipped.
