# Meta wizard

**Meta wizard …** (Ctrl+Shift+T) edits the tags of music files (MP3, FLAC, Ogg, Opus, M4A, WMA, WAV), similar to MP3TAG, and the metadata of photos, videos and documents (see below).

## Basics
- The track list shows the files of the current folder with their tags. Choose columns by right-clicking the column headers; you can also create your own fields there.
- You edit the selected tracks in the sidebar. With several tracks that have different values it shows `< keep >`: whatever you don’t touch stays as it is in each file.
- **Double-click a cell** to edit the value directly in the list – for that one row only. **Enter** applies, **Esc** cancels. Double-clicking the **file name** renames the file (the extension stays). For long texts (description, comment, lyrics) the double-click jumps to the field in the sidebar. As always nothing is written before “Save tag”.
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
  2. an ID in the file or folder name in Jellyfin style, e.g. `Alien (1979) [imdbid-tt0078748].mkv` (see “File names and IDs”)
  3. otherwise a search for title and year from the file name, e.g. `Alien (1979).mkv`. If there is exactly one match with that year it is used, otherwise you choose the movie from a list (or “Skip”). If the search finds nothing, PanePilot tries again with umlauts (`ae` → `ä`, `oe` → `ö`, `ue` → `ü`, `ss` → `ß`) and then without the year.
- **Not found or wrong movie?** In the overview a movie that was not found has the button **“Search manually …”**: adjust title and year or enter an ID (`tt0078748` or the TMDB number), then pick the movie from the result list. For a movie that was found, right-click and choose **“Search for a different film …”** (for series “Search for a different series …”, which then applies to all episodes of the series).
- **Sources:**
  - **TMDB** (The Movie Database) if an API key is entered in the settings: all data including plot summary and poster.
  - **Wikidata** if no key is entered: no account needed, but no plot summary and no poster.
- **Language:** title, plot summary and genre come in the **program language** (German for Franconian and Saxon). If there is no version in that language, English is used.
- **Overview:** before applying, PanePilot shows “field – current – new” for each movie. Only fields that are empty so far are checked; existing values are only overwritten if you tick them. The buttons “All fields” and “Only empty fields” set the ticks for all movies.
- **Without overview:** in **Settings → Meta wizard → Online data** you can choose: with overview (default), without overview filling only empty fields, or without overview overwriting everything (including the poster). With several matches the selection list still appears – if none fits, **“Search manually …”** lets you enter title, year or an ID. Movies (or series) that were not found are offered one after another for a manual search before anything is applied (“Not found (1/3)”, with Skip and Cancel). At the end a message shows how many movies were applied, not found or skipped – and which movie or episode was applied to each file (to check for wrong matches). Nothing is written until “Save tags”.
- **Apply** marks the values in green; nothing is written until **“Save tags”**, and “Undo” works as usual.
- **With TMDB only** there are also `Actors` (the first 5 cast members), `Rating` (TMDB rating, e.g. `7.8`) and `Certification` (age rating for the country of the program language, e.g. `PG-13`) – like all fields only as a proposal.
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

- **Removing tracks:** tick audio or subtitle tracks in the column **“Remove”**. A **new file** `Film-Copy.mkv` (or `.mp4`) is created in the same folder; the **original stays unchanged** – you decide what happens to it afterwards. With the tick **“Replace original (no copy)”** the checked new file replaces the original instead; PanePilot remembers the choice. The video track and the last audio track cannot be removed; if the removed track was “Default”, the next one takes over. Clicking the column header **“Remove”** ticks all tracks, a second click unticks them all – handy if you only want to keep a few. The first audio track is kept anyway. **“Forced”** works the same way.
- **Adding subtitles:** for a single video, **“Add subtitles …”** adds subtitle files as new tracks. Matching files from the folder are already listed (e.g. `Film.eng.srt` and `Film.eng.forced.srt` for `Film.mkv`), others via **“Other file …”**. Language and “forced” come from the file name and can be changed, as can the name. The result is saved like removing: as `Film-Copy.mkv` or, with “Replace original”, into the original file; the subtitle file stays. For MP4, text subtitles are converted (formatting is lost); image subtitles (`.sup`, `.idx`) only fit into MKV. Older SRT files in the Windows character set are recognised.
- **Exporting subtitles:** when removing, **“Save subtitles as files before removing”** is ticked. The button **“Export subtitles”** saves the selected (otherwise all) subtitles without removing them. Text subtitles become `.srt`, ASS subtitles `.ass`, image subtitles keep their original format (`.sup` or `.idx` + `.sub`). The files are named as usual for Jellyfin, e.g. `Film (2001).eng.srt` or `Film (2001).eng.forced.srt`.

## Changing the format
**“Change format …”** repacks the selected videos without re-encoding (no quality loss) into another format: **MP4, M4V, MOV, AVI as well as MTS and M2TS (camcorder) → MKV** or **MKV → MP4**.
- A **new file** is created in the same folder, e.g. `Film.mkv` next to `Film.mp4`; if that exists, `Film-Copy.mkv`. The original stays unchanged – unless **“Delete original afterwards”** is ticked: then it is deleted after a successful, checked conversion.
- Title, year, genre, description, author, all custom fields (e.g. `imdbid`, `Season`), cover, track languages and names as well as chapters are taken over.
- MP4 cannot hold image subtitles (PGS, VobSub) or audio formats such as DTS or TrueHD; such files are skipped and listed. Text subtitles are converted for MP4 (formatting is lost).
- This takes about as long as copying and needs as much free space; “Cancel” discards the file being created. MKV as target needs mkvtoolnix, MP4 needs ffmpeg.
- Subtitle files next to the video (`Film.eng.srt`) are left alone and still match.

## Chapters
**“Chapters …”** edits the chapters of the selected MKV and MP4 videos.
- **One video:** the table shows the existing chapters with time and name. Both can be edited directly (time e.g. `00:12:30` or `01:02:03.500`); **“Add chapter”** inserts a chapter after the selected row, **“Delete selected”** removes rows. Chapters are sorted by time.
- **Fixed interval:** **“Every … minutes”** and **“Create chapters”** sets chapters from 00:00 at the chosen interval (default 10 minutes, remembered), named “Chapter 01”, “Chapter 02” … This also works for several selected videos at once.
- **Read from file:** TXT in ChapterDB format (`CHAPTER01=00:00:00.000` / `CHAPTER01NAME=…`, e.g. from the chapterdb.plex.tv archive), Matroska XML or a simple list with one line per chapter (“00:12:30 Arrival”). If a file with the same name lies next to the video (`Film.chapters.txt`, `Film.xml`), there is a button for it. Quotes around names are removed, as is an empty final chapter. Chapters after the end of the film are left out; if the file apparently belongs to a different version, a warning appears.
- **Save as file:** writes the chapters as `Film.chapters.txt` (ChapterDB format) or as Matroska XML.
- New chapters replace the old ones; **“Delete all chapters”** removes them.
- **Saving:** MKV directly in the file (fast, no copy). MP4 is rewritten – as `Film-Copy.mp4` or, with “Replace original”, instead of the original. Chapter names get the language of the user interface.

## Downloading subtitles (OpenSubtitles)
**“Search subtitles …”** searches **opensubtitles.com** for subtitles for the selected videos.
- **One-time setup:** create a free account on opensubtitles.com, create your own API key under **“API Consumers”** in your profile and enter it under **Settings → Meta wizard → Subtitles (OpenSubtitles)**. Username and password are optional: without login **5 downloads per day** are possible, more with a free account. **“Check”** tests the access and shows the remaining downloads. Key and password are only stored in the keyring.
- **Languages:** as codes in the settings, e.g. `de, en` (default).
- **Search:** by file fingerprint and ID (`imdbid`/`themoviedb`, for series with season and episode), otherwise by title and year from the file name. Searching does not count against the quota.
- **Result list:** one group per video with language, release name, downloads, rating and the flags **“exact match”** (uploaded for exactly this file), **“forced”** and **“hearing impaired”**. The best hit per language is preselected: “exact match” first, then full subtitles before forced and hearing-impaired ones, then the most downloads.
- **Saved** next to the video as in Jellyfin: `Film.eng.srt`, `Film.eng.forced.srt`, `Film.eng.sdh.srt`; if the name exists, `Film.eng.2.srt`.
- **“Add directly to the video”** also puts the subtitles as a track into MKV and MP4 files – as `Film-Copy.mkv` or, with “Replace original”, into the original file (as with “Add subtitles”).

## Online data for TV series
**“Online data (movies, series) …”** recognises episodes by the pattern **`S01E02`** in the file name (also `s1e2` or `1x02`).
- **Without `S01E02`:** if the files are only called `1.mkv`, `2.mkv` … or `Folge 3`, `Teil 3`, `Episode 3` or `E03`, PanePilot asks once per folder whether they are episodes of the series named by the folder (e.g. “Treat the 6 files in ‘Auf Leben und Tod’ as episodes 1–6 of season 1?”). In a folder `Season 2` they count as season 2, otherwise season 1. With “No” they are searched as movies.
- **Series name:** from the folder, e.g. `Breaking Bad/Season 1/Breaking Bad - S01E02.mkv` or `Breaking Bad (2008) [tmdbid-1396]/S01E02.mkv`; otherwise from the file name before `S01E02`.
- The series is searched **once per series**; with several matches you choose it once, and it applies to all episodes.
- **Fields:** title (episode title), `Series`, `Season` and `Episode` (two digits, e.g. `01`), year of first broadcast, episode summary, genre of the series, season poster as cover and `themoviedb` (ID of the series). In MP4, series, season and episode are also written to the iTunes standard fields.
- Series need a **TMDB key**; without a key a note appears, movies still come from Wikidata.
- If an **ID** is on the series folder, the season folder or the episode, PanePilot does not search but takes the series directly (see “File names and IDs”).
- With **tag → file name** and `%Series% - S%Season%E%Episode% - %title%` you can then name the episodes consistently, e.g. `Breaking Bad - S01E02 - Cat's in the Bag.mkv`.

## File names and IDs
With an ID in the name PanePilot finds the movie or series reliably, without searching or choosing. The notation is the same as in **Jellyfin** – folders named this way work for both programs.
- **Notation:** prefix, hyphen, ID, in square, round or curly brackets:
  - `[imdbid-tt0078748]` or `[imdb-tt0078748]` – IMDb (the number starts with `tt`)
  - `[tmdbid-348]` or `{tmdb-348}` – TMDB (the number from the address `themoviedb.org/movie/348` or `…/tv/873`)
  - `[tvdbid-73584]` or `(tvdb-73584)` – TheTVDB
  - Several IDs in one name are allowed. A bare number such as `[tt0078748]` without prefix is – as in Jellyfin – **not** recognised.
- **Movies:** ID in the file name, e.g. `Alien (1979) [imdbid-tt0078748].mkv`, or in the folder directly above, e.g. `Alien (1979) [imdbid-tt0078748]/Alien.mkv`. The ID in the file name wins.
- **Series:** ID on the **series folder**, e.g. `Columbo (1971) {tmdbid-873}/Season 1/Columbo S01E01.mkv` or `Columbo [imdbid-tt1466074]/…`. It also works on the season folder (`Season 01 [tvdbid-73584]`) or on the episode (`Columbo S01E01 [imdbid-tt0065189].mkv`). Season and episode always come from `S01E01`. If the IMDb ID is that of a single episode, PanePilot takes the series it belongs to. For series, `tmdbid-` always means the number of the series.
- PanePilot looks up IMDb and TVDB IDs at TMDB; without a TMDB key only the IMDb ID of movies works (via Wikidata).
- Custom fields `imdbid`/`themoviedb` in the tag win for movies; for series the ID in the name wins.

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
