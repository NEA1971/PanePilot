# Meta wizard

**Meta wizard …** (Ctrl+T) edits the tags of music files (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV), similar to MP3TAG, and the metadata of photos, videos and documents (see below).

## Basics
- The track list shows the files of the current folder with their tags. Choose columns by right-clicking the column headers; you can also create your own fields there.
- You edit the selected tracks in the sidebar. With several tracks that have different values it shows `< keep >`: whatever you don’t touch stays as it is in each file.
- Changes are only **pending** at first and marked green. **Save tag** writes them to the files. **Undo** reverts the last save.
- **Cover**: drag an image in, or right-click the cover to load, save or remove it.

## Converters
- **File name → tag**, **tag → file name**, **tag → tag**: with format strings like `%track% - %title%`, with a preview and templates.
  - Examples for **file name → tag**. `%dummy%` skips a part of the name; custom fields are written like placeholders, e.g. `%Season%`:
    - `01 - Intro.mp3` → `%track% - %title%`
    - `Alien (1979).mkv` → `%title% (%year%)`
    - `Battlestar Galactica (2003) - S01E09 - Tigh Me Up.mkv` → `%dummy% - S%Season%E%Episode% - %title%` (Season “01”, Episode “09”, title “Tigh Me Up”)
- **Tag → text file/CSV** and **text file → tag**: for editing in LibreOffice or for taking over a track list from the internet. In the assignment window, placeholders make up for missing lines.
  - **Table from LibreOffice Calc:** a column **“File name”** (exact name including extension) and further columns headed e.g. “Title”, “Year” or custom field names. Save as **Text CSV** with semicolon or comma as separator, UTF-8, **without “Fixed column width”**. PanePilot then matches the rows by file name.
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

## Videos
If the folder contains videos, the meta wizard shows their metadata. If several kinds are mixed, choose what to show with **“Music | Photos | Videos”** at the top; the kind with the most files is preselected. Files ending in `.mp4` always count as video, `.m4a` as music.
- **Read and write**: MP4, MOV, M4V, 3GP and WMV. **MKV and WebM** only if the **mkvtoolnix** package is installed (`sudo apt install mkvtoolnix`), otherwise read-only. **AVI** and **MTS/M2TS** (camcorders) are read-only.
- **Edit**: title, description, author, copyright, genre, year and date taken, plus **custom fields** as for music.
- **Duration, resolution, frame rate, video and audio codec and bitrate** are read with the **ffmpeg** program (`sudo apt install ffmpeg`). Without ffmpeg this information is missing.
- **Date taken and GPS**: for MP4/MOV the date taken can only be changed, and GPS only removed, with **exiftool** (`sudo apt install libimage-exiftool-perl`). For MKV/WebM mkvtoolnix changes the date. For WMV the date cannot be changed. **Show on map** opens the position in OpenStreetMap.
- **Audio tracks and subtitles**: the optional columns **Audio tracks** and **Subtitles** show the languages of the tracks contained, as stored in the file, e.g. `deu, eng` or `eng (forced)`; `?` means “no language set”. Hovering shows one line per track with the language name, format and flags, e.g. “deu (German) – AC-3 5.1 – default”. The information comes from ffmpeg and can only be viewed here, not changed. Subtitles in separate files (`.srt` next to the video) are not counted.
- **Extension does not match the content**: PanePilot recognises the real format from the start of the file, not from the extension. If, for example, an MKV video is saved as `.mp4`, it is still read and written correctly. The **Format** column then shows the real format first and the file's extension in brackets, e.g. **“MKV (.mp4)”**. So that such files stand out in long lists, the whole row is shown in **bold blue**, and the sidebar points this out (a pending change makes the row green, an error red). If format and extension match, only the format is shown as usual, e.g. “MP4”. It is best to rename such files so that the extension is correct.
- **Thumbnail (poster)**: the sidebar shows the thumbnail stored in the video. If there is none, it shows a still frame from the video (at about 10 % of the running time). Right-click to replace, remove or save the thumbnail; **“Use still frame as thumbnail”** stores the frame shown as the poster in the video.
- **Converters** for videos: as for photos, i.e. tag → file name, file name → tag, tag → tag, tag → text file/CSV, text file → tag and **Shift date …**.
  - Placeholders: `%datetaken%`, `%title%`, `%author%`, `%genre%`, `%year%` …, plus `%duration%`, `%resolution%`, `%width%`, `%height%`, `%fps%`, `%codec%`, `%audiolang%`, `%sublang%` and `%format%`.
  - `$date(%datetaken%,JJJJ-MM-TT_hhmmss)` gives e.g. `2026-11-08_150012.mp4`.
  - Videos usually store the date taken in universal time (UTC); PanePilot shows it in the computer’s local time.

## Online data for movies
In video mode the button **“Online data (movies, series) …”** fetches title, year, genre, plot summary, director and poster from the internet for the selected videos (without a selection for all shown).
- **How PanePilot knows which movie it is**, in this order:
  1. custom fields `imdbid` or `themoviedb`
  2. an ID in the file name in Jellyfin style, e.g. `Alien (1979) [imdbid-tt0078748].mkv` or `[tmdbid-348]`
  3. otherwise a search for title and year from the file name, e.g. `Alien (1979).mkv`. If there is exactly one match with that year it is used, otherwise you choose the movie from a list (or “Skip”).
- **Sources:**
  - **TMDB** (The Movie Database) if an API key is entered in the settings: all data including plot summary and poster.
  - **Wikidata** if no key is entered: no account needed, but no plot summary and no poster.
- **Language:** title, plot summary and genre come in the **program language** (German for Franconian and Saxon). If there is no version in that language, English is used.
- **Overview:** before applying, PanePilot shows “field – current – new” for each movie. Only fields that are empty so far are checked; existing values are only overwritten if you tick them. The buttons “All fields” and “Only empty fields” set the ticks for all movies.
- **Apply** marks the values in green; nothing is written until **“Save tags”**, and “Undo” works as usual.
- A missing ID is added: a movie with `imdbid` also gets `themoviedb` and vice versa. If the original title differs from the title, it goes into the field `originaltitle`. The poster (about 500 pixels wide) is stored as cover in MP4, MKV and WMV.
- AVI files cannot be tagged; they appear in the overview with “format is read-only”.

### Getting a TMDB API key
1. Create a free account on **themoviedb.org** and confirm the e-mail.
2. Click the profile picture at the top right → **Settings** → **API** and request a key (“Developer”, personal use). The application details are informal, e.g. “PanePilot, private movie collection”.
3. Copy the **API key** (32 characters) or the long **API read access token**.
4. In PanePilot: **Settings → Meta wizard → Online data for movies**, paste the key, **“Check”**, then **OK**.

The key is only stored in your keyring, not in the settings files. This product uses the TMDB API but is not endorsed or certified by TMDB.

## Editing tracks (MKV and MP4)
In video mode **“Tracks …”** opens a table of all tracks of the selected MKV and MP4 videos: video, audio and subtitles, each with format, language, name and the flags “Default” and “Forced”.
- **Language:** choose from the list, e.g. “German (ger)”, or type a code. The “Audio tracks” column then shows `ger` instead of `?`.
- **Name:** enter freely or let **“Suggest names”** build one, e.g. “German AC3 5.1” (for the selected rows, otherwise for all). Players like VLC show this name instead of “Track 1”.
- **Default** is the track a player picks first; **Forced** shows subtitles only for foreign-language parts. For video tracks only the name can be changed.
- **Several videos at once:** tracks are grouped by number (“Audio 1”, “Subtitle 1” …). A change applies to this track in all selected videos. Differing values appear as “different” and stay unchanged unless you change them. Videos without the track are skipped and listed beforehand.
- **Saving:** “Apply” asks once more and then writes to the files **immediately** (with mkvpropedit, in seconds, also on a NAS). There is no “Undo” for this.
- **MKV** needs **mkvtoolnix** (`sudo apt install mkvtoolnix`).
- **MP4** (also M4V and MOV):
  - The **language** is changed directly in the file, in seconds. MP4 requires the codes `deu`, `fra`, `nld` … instead of `ger`, `fre`, `dut`; PanePilot converts automatically.
  - **Track name** and **“Default”** need a new file: PanePilot repacks it with ffmpeg (no re-encoding, no quality loss). This takes about as long as copying the file and temporarily needs as much free space; a confirmation points this out beforehand, the progress bar has “Cancel”. Tags, custom fields (e.g. `imdbid`, `Season`) and cover are taken over; the old file is only replaced once the new one has been checked.
  - **“Forced”** is greyed out for MP4 because MP4 hardly supports it.

- **Removing tracks:** tick audio or subtitle tracks in the column **“Remove”**. A **new file** `Film-Copy.mkv` (or `.mp4`) is created in the same folder; the **original stays unchanged** – you decide what happens to it afterwards. The video track and the last audio track cannot be removed; if the removed track was “Default”, the next one takes over.
- **Exporting subtitles:** when removing, **“Save subtitles as files before removing”** is ticked. The button **“Export subtitles”** saves the selected (otherwise all) subtitles without removing them. Text subtitles become `.srt`, ASS subtitles `.ass`, image subtitles keep their original format (`.sup` or `.idx` + `.sub`). The files are named as usual for Jellyfin, e.g. `Film (2001).eng.srt` or `Film (2001).eng.forced.srt`.

## Changing the format
**“Change format …”** repacks the selected videos without re-encoding (no quality loss) into another format: **MP4, M4V, MOV and AVI → MKV** or **MKV → MP4**.
- A **new file** is created in the same folder, e.g. `Film.mkv` next to `Film.mp4`; if that exists, `Film-Copy.mkv`. The original stays unchanged.
- Title, year, genre, description, author, all custom fields (e.g. `imdbid`, `Season`), cover, track languages and names as well as chapters are taken over.
- MP4 cannot hold image subtitles (PGS, VobSub) or audio formats such as DTS or TrueHD; such files are skipped and listed. Text subtitles are converted for MP4 (formatting is lost).
- This takes about as long as copying and needs as much free space; “Cancel” discards the file being created. MKV as target needs mkvtoolnix, MP4 needs ffmpeg.
- Subtitle files next to the video (`Film.eng.srt`) are left alone and still match.

## Online data for TV series
**“Online data (movies, series) …”** recognises episodes by the pattern **`S01E02`** in the file name (also `s1e2` or `1x02`).
- **Series name:** from the folder, e.g. `Breaking Bad/Season 1/Breaking Bad - S01E02.mkv` or `Breaking Bad (2008) [tmdbid-1396]/S01E02.mkv`; otherwise from the file name before `S01E02`.
- The series is searched **once per series**; with several matches you choose it once, and it applies to all episodes.
- **Fields:** title (episode title), `Series`, `Season` and `Episode` (two digits, e.g. `01`), year of first broadcast, episode summary, genre of the series, season poster as cover and `themoviedb` (ID of the series). In MP4, series, season and episode are also written to the iTunes standard fields.
- Series need a **TMDB key**; without a key a note appears, movies still come from Wikidata.
- With **tag → file name** and `%Series% - S%Season%E%Episode% - %title%` you can then name the episodes consistently, e.g. `Breaking Bad - S01E02 - Cat's in the Bag.mkv`.

## Documents
Office files and PDFs can be tagged in the meta wizard as well. In mixed folders choose **“Documents”** in the **“Music | Photos | Videos | Documents”** switch at the top. No additional programs are needed.
- **Read and write**: Word, Excel and PowerPoint (DOCX, XLSX, PPTX, also DOCM, XLSM, PPTM), LibreOffice/OpenDocument (ODT, ODS, ODP, ODG) and **PDF**.
- **Read-only**: the old Office formats **DOC, XLS, PPT**, **encrypted PDFs** and **digitally signed PDFs**. For signed PDFs any change would invalidate the signature; the sidebar points this out.
- **Editable**: title, subject, author, keywords, description, category and language, plus **custom fields** via “Insert field”. They are stored as “custom properties”, which Word and LibreOffice also show under **File → Properties**. PDF has no description and no category, OpenDocument has no category.
- **View only**: created, modified, last saved by, application (for PDF the creator and producer), pages, words and PDF version, as far as the file contains them. Saving the metadata does not change them.
- **Where it is written**: for Office into the document properties of the file, for PDF into the document information and additionally into the XMP metadata if the PDF has any. The content of the file stays unchanged.
- Separate **keywords** with semicolons, e.g. `tax; 2026`.
- **Preview**: for PDF the sidebar shows the first page, for Office files the thumbnail that Word, Excel or LibreOffice stored in the file (if any).
- **Converters**: tag → file name, file name → tag, tag → tag, tag → text file/CSV and text file → tag.
  - Placeholders: `%title%`, `%subject%`, `%author%`, `%keywords%`, `%created%`, `%modified%`, `%application%`, `%pages%`, `%words%` and `%format%`.
  - `$date(%created%,JJJJ-MM-TT) %title%` gives e.g. `2026-11-17 Offer.pdf`.

The chapter **Additional programs** lists the programs PanePilot can use.
