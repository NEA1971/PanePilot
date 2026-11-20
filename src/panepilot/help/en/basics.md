# Basics

PanePilot shows two file panels side by side. One of them is **active**, recognizable by its coloured path bar. Most commands apply to the selected entries in the active panel. Copying and moving always go **to the other panel**.

## Navigating
- **Double-click** or **Enter** opens a folder or opens a file with its default program.
- **Backspace** goes one level up. The mouse buttons “Back” and “Forward” work like in a browser.
- **Tab** switches between the panels.
- You can type a path directly into the **path bar**.
- In the **Navigate** menu: same folder in the other panel, swap panels, back, forward.

## Working with files
- **Copy / Move** to the other panel (F5 / F6) asks first; the “without asking” variants start right away. Drag and drop works too, also to and from Nautilus.
- **Rename** (F2), **New folder** (F7), **New text file** (Shift+F4), **Move to trash** (F8), **Delete permanently**. When renaming, the input field always shows the complete name including the extension – also in the “Name (without extension)” column. The part before the extension is preselected; the extension can be changed as well.
- **Clipboard**: copy, cut, paste (Ctrl+C/X/V), also together with other programs.
- **Duplicate** (Ctrl+D, also in the context menu): creates a copy of the selected files and folders in the same folder without asking – `Report.docx` becomes `Report-Copy.docx`, the next time `Report-Copy-2.docx`. The copies are selected afterwards, e.g. for renaming with F2. Not available on FTP/SFTP servers.
- **Panels one above the other** (View → “Panels one above the other”, Ctrl+Shift+H): shows the two panels one above the other instead of side by side. Each panel keeps its sidebar on the left, the button bar lies horizontally in between. The layout is remembered separately for both arrangements.
- **Refresh** (Ctrl+R, also at the bottom of the context menu): re-reads the shown folder; the selection is kept.
- **Open with**: right-click a file to see matching programs; “Other application …” shows all.
- **Archives**: compress and extract via the context menu.
- **Properties** (Alt+Enter) shows size, permissions, dates and the metadata of music, photos, videos and documents.
- **Open terminal here** (File menu or right-click): opens the default terminal in the shown folder, or in the folder you right-clicked.
- **Create directory listing …** (File menu or right-click): writes an indented list of the folder with sizes and modification dates to a text file. You choose the depth, whether files and hidden entries are included and whether to open the list afterwards.

## View
- **Filter** (View menu): shows only matching entries, e.g. `*.mp3`. Separate several patterns with a semicolon or comma, e.g. `*.mkv;*.mp4`. An active filter turns the path bar red.
- **Hidden files**, **single-panel view**, button bar, function key bar and toolbar can be switched in the **View** menu.
- Columns: right-click the column headers. Order and width are set directly by dragging (see [Settings](settings.md)).

## Icon view
- **View → Icon view** (Ctrl+Shift+I) shows the active panel with large icons instead of a list; each panel remembers its view.
- Three sizes via **View → Icon size** or **Ctrl+mouse wheel**.
- **Thumbnails:** images, the first page of PDFs, the cover of music files and the poster of videos (otherwise a frame from the film). Thumbnails already in the shared cache `~/.cache/thumbnails` (e.g. from Nautilus) are used at once; missing ones are created in the background and stored there.
- Selecting, keyboard, copying, dragging and the context menu work as in the list. Sort via **View → Sort by**.

## Favourites
- **Add to favourites** remembers the current folder. Favourites can be grouped and appear in the sidebar and in the **Favourites** menu.

See also: [Sidebars](sidebars.md) · [Keyboard shortcuts](shortcuts.md)
