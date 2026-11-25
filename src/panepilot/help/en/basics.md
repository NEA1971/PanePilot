# Basics

PanePilot shows two file panels side by side. One of them is **active**, recognizable by its coloured path bar. Most commands apply to the selected entries in the active panel. Copying and moving always go **to the other panel**.

## Navigating
- **Double-click** or **Enter** opens a folder or opens a file with its default program.
- **Backspace** goes one level up. The mouse buttons “Back” and “Forward” work like in a browser.
- **Tab** switches between the panels.
- You can type a path directly into the **path bar**.
- In the **Navigate** menu: same folder in the other panel, swap panels, back, forward.
- **Recently visited folders**: the arrow at the right of the path bar (or Alt+↓) shows the last 20 folders of both panels, newest first; the list is remembered on exit.

## Tabs
- Each panel can have several **tabs**: **Ctrl+T** opens a new tab with the current folder, **Ctrl+W** closes it, **Ctrl+Tab** / **Ctrl+Shift+Tab** switch.
- A new tab also opens with the **middle mouse button** or **Ctrl+double-click** on a folder, via **“Open in new tab”** in the context menu (also for several selected folders) and by double-clicking the empty tab bar. The middle button on a tab closes it; tabs can be reordered by dragging.
- Every tab has its own folder, history, sorting, filter and view (details/icons); columns and sidebar apply to the whole panel.
- **Right-click a tab**: new tab, close, close others, lock/unlock, open in other panel. A **locked tab** (🔒) stays put – changing the folder in it opens a new tab.
- The tab bar appears from the second tab on (Settings → File view → Tabs: “always show”). While search, multi-rename, meta wizard, synchronization or a server connection run, the tabs of that panel are locked. All tabs are remembered on exit. The **“Tabs”** toolbar button switches “always show the tab bar” on and off; its arrow menu has Open in new tab, New/Next/Previous tab, Close tab and Lock tab.

## Working with files
- **Copy / Move** to the other panel (F5 / F6) asks first; the “without asking” variants start right away. Drag and drop works too, also to and from Nautilus.
- **Rename** (F2), **New folder** (F7), **New text file** (Shift+F4), **Move to trash** (F8), **Delete permanently**. When renaming, the input field always shows the complete name including the extension – also in the “Name (without extension)” column. The part before the extension is preselected; the extension can be changed as well.
- **Clipboard**: copy, cut, paste (Ctrl+C/X/V), also together with other programs.
- **Paths and names to the clipboard** (Edit menu, right-click → “To clipboard” or the arrow at the “Copy” button): file path (Alt+Ins), file name (Alt+Shift+Ins), file name without extension, folder path, file path as address (`file:///…`) and details (name, size in bytes, date, type – tab-separated, e.g. for pasting into Excel). With several selected files, each is on its own line.
- **Duplicate** (Ctrl+D, also in the context menu): creates a copy of the selected files and folders in the same folder without asking – `Report.docx` becomes `Report-Copy.docx`, the next time `Report-Copy-2.docx`. The copies are selected afterwards, e.g. for renaming with F2. Not available on FTP/SFTP servers.
- **Panels one above the other** (View → “Panels one above the other”, Ctrl+Shift+H): shows the two panels one above the other instead of side by side. Each panel keeps its sidebar on the left, the button bar lies horizontally in between. The layout is remembered separately for both arrangements.
- **Refresh** (Ctrl+R, also at the bottom of the context menu): re-reads the shown folder; the selection is kept.
- **Open with**: right-click a file to see matching programs; “Other application …” shows all.
- **Archives** (“Archive” button or right-click → “Archive ▸”): **Open**, **Extract here**, **Extract to …**, **Extract to “name”** (own folder) and **Create archive …**. Clicking the button opens the selected archive; if none is selected, it starts “Create archive …”.
- **Archives like folders:** double-click or Enter on a zip, tar, 7z or rar archive shows its contents in the panel (path e.g. `…/Photos.zip/Holiday`); “..” leads back out. Files inside can be opened and copied to the other panel with F5 or by dragging – which extracts them.
- **Writing to archives** (ZIP and TAR without extra programs, 7z with 7-Zip; RAR stays read-only): **F5** or dragging from the other panel copies into it (same names bring up the same question as copying), **F6** moves into it (originals go to the trash afterwards) or out of it (extract, then delete in the archive), **F7** creates a folder, **F2** renames, **F8**/Del deletes – **permanently** inside an archive, after asking. PanePilot first writes a copy next to the archive and replaces the original only when everything worked; on errors or cancelling it stays unchanged. If you opened a file from the archive and save it, PanePilot asks whether to write the change back (while PanePilot is running). Password-protected archives can be written with 7-Zip and the password you entered. For password-protected archives PanePilot asks for the password (it is not stored). To open archives with the default application instead, change Settings → File view → Archives. 7z and rar need 7zip or unrar, AES-encrypted ZIPs need 7zip as well.
- **Properties** (Alt+Enter) shows size, permissions, dates and the metadata of music, photos, videos and documents.
- **Open terminal here** (File menu or right-click): opens the default terminal in the shown folder, or in the folder you right-clicked.
- **Create directory listing …** (File menu or right-click): writes an indented list of the folder with sizes and modification dates to a text file. You choose the depth, whether files and hidden entries are included and whether to open the list afterwards.

## View
- **Filter** (View menu): shows only matching entries, e.g. `*.mp3`. Separate several patterns with a semicolon or comma, e.g. `*.mkv;*.mp4`. An active filter turns the path bar red.
- **Hidden files**, **single-panel view**, button bar, function key bar and toolbar can be switched in the **View** menu.
- Columns: right-click the column headers. Order and width are set directly by dragging (see [Settings](settings.md)).

## Quick view
- Button **“Quick view”** (magnifier over a sheet, right of “View”) or **View → Quick view**: the **other panel** shows the selected file instead of the file list. Moving with the arrow keys updates the preview. Another click or **Esc** brings the list back. No key is assigned by default – choose one under Settings → Keyboard shortcuts or the function keys.
- Shown: **text** (the first 1 MB), **images** (fitted, the mouse wheel zooms), **PDF** (all pages one below the other), **videos** (a still with duration, resolution and tracks), **music** (cover and tags), **LibreOffice and Microsoft documents** (Writer/Word as text, Calc/Excel as a table with one tab per sheet – the first 500 rows –, Impress/PowerPoint slide by slide as text). Other files show type, size and date, folders the number of items.
- Quick view needs both panels; it is not available in single-panel view or while the other panel shows something else (e.g. the meta wizard).

## Selection, folder sizes, comparing, dates
- **Select by pattern** (Edit menu): **Num +** extends the selection, **Num −** reduces it – prefilled with the extension of the current file, e.g. `*.jpg`, several patterns with `;`, recent patterns are offered, “Include folders” counts folders too. **Num \*** inverts the selection, **Alt+Num +** selects all files with the same extension as the current one.
- **Folder sizes:** **Space** on a folder shows its size in the “Size” column. **View → Calculate all folder sizes** (Alt+Shift+Enter) does this for all folders in the panel, in the background – **Esc** cancels. The values stay until you leave the folder or choose “Refresh”; the selection total in the status line includes them.
- **Compare files …** (right-click or File menu, Ctrl+Shift+C): compares **two selected files** – both in one panel or one on each side. Text files appear side by side with coloured differences (yellow changed, red left only, green right only), both sides scroll together, **▲ / ▼** (Alt+↑ / Alt+↓) jump to the previous/next difference. PDF, LibreOffice and Microsoft documents are compared by their text. For other files PanePilot reports “identical” or the position of the first difference.
- **Change date …** (right-click or File menu): sets the modification date to a fixed date, to now, to the **date taken** (photos/videos) or to a date in the **file name** (e.g. `IMG_20240512_143012.jpg`). The preview shows old → new; files without a matching date stay unchanged. “Include subfolders” applies it to everything inside. The creation date cannot be set on Linux.
- **Permissions for subfolders:** Properties → Permissions → “Also for subfolders and contained files”. Folders get the “execute” right so they can still be opened.

## Shared sidebar
- **View → Shared sidebar** shows **one sidebar on the far left** over the full height instead of two – side by side as well as one above the other.
- It always belongs to the **active panel**: click into the other panel and the folder tree shows its folder, favorites open there. View and favorites set stay the same.
- **Tools** (multi-rename, search, checksums, meta wizard) stay with the panel they were started in until you close them.
- The View menu then has a single “Sidebar” entry. The width is remembered per layout.

## Icon view
- **“View” button** in the toolbar (via “Customize toolbar”): a click switches between details and the last icon size, the arrow next to it offers large, medium and small icons and details; the dot marks the current view.
- **View → Icon view** (Ctrl+Shift+I) shows the active panel with large icons instead of a list; each panel remembers its view.
- Three sizes via **View → Icon size** or **Ctrl+mouse wheel**.
- **Thumbnails:** images, the first page of PDFs, the cover of music files and the poster of videos (otherwise a frame from the film). Thumbnails already in the shared cache `~/.cache/thumbnails` (e.g. from Nautilus) are used at once; missing ones are created in the background and stored there.
- Selecting, keyboard, copying, dragging and the context menu work as in the list. Sort via **View → Sort by**.

## Favourites
- **Add to favourites** remembers the current folder. Favourites can be grouped and appear in the sidebar and in the **Favourites** menu.

See also: [Sidebars](sidebars.md) · [Keyboard shortcuts](shortcuts.md)

## Windows
- **Installing:** `PanePilot-…-windows-x64-setup.exe` installs to `C:\Program Files\PanePilot` (administrator rights), with a Start menu entry and optionally a desktop icon; uninstall via “Apps & features”. Alternatively there is the **portable ZIP**. As PanePilot is not signed, Windows warns on the first start: “More info” → “Run anyway”. Settings are stored in `%APPDATA%\PanePilot`.
- **Trash:** as on Linux – show, restore, delete permanently and empty work with the Windows Recycle Bin.
- **Open with:** shows the programs registered for the file type; “Other application …” opens the Windows “Open with” window.
- **Drives:** in the folder tree **This PC** lists all drives with their labels, network drives included. **File → Map network drive … / Disconnect …** (also by right-clicking the folder tree) opens the Windows window for it.
- **Network:** two ways lead to a share. (1) Type `\\NAS` into the path bar – the server's shares appear as folders; `\\NAS\Share` opens the share directly. (2) In the folder tree under **Network**: it lists the computers Windows finds on the network and the servers you added yourself (right-click “Network” → **Add server …**, on one of your servers → **Remove server**). Clicking a server shows its shares; each server appears only once, however it was found. If the server asks for a login, the Windows login window opens (with “Remember my credentials”). Right-click a share → **Map as network drive …** gives it a drive letter. Searching the network can be switched off under Settings → File view → Network; then only your own servers are listed.
- **Backup from the other system:** if you restore a backup from your Linux PC on Windows (or the other way round), PanePilot asks whether to apply the settings only – toolbar, shortcuts, columns, function keys, language etc. Favorites, last opened folders, saved sync profiles and servers then stay as they are, as their paths would not fit the other system.
- **Attributes:** instead of permissions, owner and group there is the **Attributes** column (R = read-only, H = hidden, S = system, A = archive) and an **Attributes** tab in the properties to change them.
- **Hidden files:** “Show hidden files” shows files with the “Hidden” attribute and names starting with a dot. Protected system files stay hidden unless you switch them on in the settings.
- **Passwords** (servers, OpenSubtitles, TMDb) are kept in the **Windows Credential Manager**.
- **Clipboard:** additionally folder path, file path and file name in short form (8.3), paths “web” (with `/`) and as UNC (`\\computer\share\…`).
- **Additional programs** (ffmpeg, exiftool, MKVToolNix, 7-Zip) are installed by you; which one is needed for what and how is described under [Additional programs](tools.md). The video functions then work as on Linux.
- **Favorites from FreeCommander:** **Favorites → Import from FreeCommander …** opens FreeCommander's settings folder with the newest `FreeCommander.fav*.xml`. It becomes a new favorite set “FreeCommander” (can be renamed like any set) with the categories as favorite folders, the folders and files and their font colour. Shortcuts, sorting and view settings from FreeCommander are left out.
- **“When finished” in synchronization:** shut down and sleep via Windows; scripts `.bat`/`.cmd` run via cmd, `.ps1` via PowerShell, other commands via cmd – with the same environment variables as on Linux (`%PANEPILOT_RESULT%` etc.).
