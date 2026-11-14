# Search

**Search …** (Ctrl+F) searches from the folder of the active panel.

- **File name**: with wildcards like `*.pdf` or `holiday*`; separate several patterns with a semicolon.
- **Contained text**: searches text files only (no images, programs, Office or PDF files). Files above 100 MB are skipped and reported.
- **Depth**: this folder only, a number of levels or unlimited.
- **Options**: search hidden files, show folders as hits, include network shares.

The hits appear in the panel like a normal folder. You can do anything with them there: copy, delete, rename, open. **Go to folder** opens the folder of a hit. **Stop** cancels a long search.

## Find duplicates
**File → Find duplicates …** (or right-click a folder) opens a separate window. PanePilot stays usable meanwhile.
- **What counts as duplicate:**
  - **a) Same content** – byte-identical files, even with different names. PanePilot compares sizes first and only reads files of equal size (SHA-256 checksum). Empty files do not count.
  - **b) Same name without extension** – e.g. `Alien (1979).mkv` and `Alien (1979).mp4`. The content is not compared. `Alien (1979).eng.srt` does not count, because its name without extension is “Alien (1979).eng”.
  - **c) Same name and same size** – fast, without checksum.
  - b) and c) are fast. a) is the most accurate but can take a long time with large files or over the network (NAS); the progress bar shows how much has been read, **Cancel** stops the search immediately.
- **Where:** start folder (changeable), **depth** 1 (this folder only) to 10 levels or unlimited, optionally **also the folder of the other panel** – e.g. to compare a backup with the original.
- **Filter:** only certain files such as `*.mp4;*.mkv` and a **minimum size** in MB. Hidden files are only included if the file panel shows them; symbolic links are not followed.
- **Result:** one group per duplicate with name, folder, size and modification date, plus a summary (groups, files, surplus files and their size).
- **Check:** individually or with **Check → all except the newest / oldest / largest** or **uncheck all**.
- **Move to trash** moves the checked files after a confirmation. If all files of a group are checked, PanePilot warns explicitly. Permanent deletion is deliberately not offered here.
- **Show in file panel** (or double-click) jumps to the file in the active panel, **Save list …** stores the groups as a text file.
- PanePilot remembers the last settings and the window size.
