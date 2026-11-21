# Search

**Search …** (Ctrl+F) searches from the folder of the active panel.

- **File name**: with wildcards like `*.pdf` or `holiday*`; separate several patterns with a semicolon or comma.
- **Contained text**: searches text files and, with the checkbox **“Also search documents (PDF, Office)”**, also PDF, Word (DOCX), Excel (XLSX), PowerPoint (PPTX) and LibreOffice (ODT, ODS, ODP). The old formats DOC, XLS and PPT and scanned PDFs without a text layer are not found. A hit's tooltip shows the matching passage, for PDFs with the page.
- **Large files:** files above 100 MB are skipped and reported after the search (hover over the message for the list). Searching documents takes longer.
- **Depth**: this folder only, a number of levels or unlimited.
- **Options**: search hidden files, show folders as hits, include network shares.

The hits appear in the panel like a normal folder. You can do anything with them there: copy, delete, rename, open. **Go to folder** opens the folder of a hit. **Stop** cancels a long search.

## Find duplicates
**File → Find duplicates …** (or right-click a folder) opens a separate window. PanePilot stays usable meanwhile.
- **What counts as duplicate:**
  - **a) Same content** – byte-identical files, even with different names. PanePilot compares sizes first and only reads files of equal size (SHA-256 checksum). Empty files do not count.
  - **b) Same name without extension** – e.g. `Alien (1979).mkv` and `Alien (1979).mp4`. The content is not compared. `Alien (1979).eng.srt` does not count, because its name without extension is “Alien (1979).eng”.
  - **c) Same name and same size** – fast, without checksum.
  - **d) Same ID in the name** – e.g. `[imdbid-tt0078748]` or `[tmdbid-348]` (the notation used by Jellyfin, Plex and Kodi). Finds the same film even if the titles are spelled differently. If a file has several IDs, the IMDb ID counts before TMDb and TVDb; files without an ID are ignored.
  - **e) Similar name** – finds typos and different spellings, e.g. “Der.Pate_1972.mkv” and “Der Pate (1972).mp4”. Extension, case, punctuation and IDs do not count; **numbers in the name must match** (otherwise “IMG_0001” and “IMG_0002” would be similar). The slider sets how similar the names must be (70–100 %, default 85 %). If A is similar to B and B to C, all three are in one group.
  - **f) Similar image/video (picture content)** – finds the same picture in another size, compression or format (JPG, PNG, WebP, HEIC, GIF, BMP, TIFF) and the same film in another resolution. Rotated, mirrored or heavily cropped pictures are not detected, RAW files are not read. Videos are compared at 5 points and their duration may differ by at most 2 %; images are only compared with images, videos with videos. Slider 70–100 %, default 90 %. The “fingerprints” are remembered in `~/.cache/PanePilot`, so a further run is fast. The list shows thumbnails and the resolution; **“Keep highest resolution”** marks all other files in each group.
  - b), c) and d) are fast. a) is the most accurate but can take a long time with large files or over the network (NAS); the progress bar shows how much has been read, **Cancel** stops the search immediately.
- **Where:** start folder (changeable), **depth** 1 (this folder only) to 10 levels or unlimited, optionally **also the folder of the other panel** – e.g. to compare a backup with the original.
- **Filter:** only certain files such as `*.mp4;*.mkv` and a **minimum size** in MB. Hidden files are only included if the file panel shows them; symbolic links are not followed.
- **Result:** one group per duplicate with name, folder, size and modification date, plus a summary (groups, files, surplus files and their size) and how many files were checked – “0 files checked” means the filter matched nothing.
- **Check:** individually or with **Check → all except the newest / oldest / largest** or **uncheck all**.
- **Move to trash** moves the checked files after a confirmation. If all files of a group are checked, PanePilot warns explicitly. Permanent deletion is deliberately not offered here.
- **Show in file panel** (or double-click) jumps to the file in the active panel, **Save list …** stores the groups as a text file.
- PanePilot remembers the last settings and the window size.
