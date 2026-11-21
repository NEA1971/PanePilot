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
- **Archives like folders:** double-click or Enter on a zip, tar, 7z or rar archive shows its contents in the panel (path e.g. `…/Photos.zip/Holiday`); “..” leads back out. Files inside can be opened (changes are not written back) and copied to the other panel with F5 or by dragging – which extracts them. Archives are read-only: deleting, renaming, copying into them and new folders are not possible. For password-protected archives PanePilot asks for the password (it is not stored). To open archives with the default application instead, change Settings → File view → Archives. 7z and rar need 7zip or unrar, AES-encrypted ZIPs need 7zip as well.
- **Properties** (Alt+Enter) shows size, permissions, dates and the metadata of music, photos, videos and documents.
- **Open terminal here** (File menu or right-click): opens the default terminal in the shown folder, or in the folder you right-clicked.
- **Create directory listing …** (File menu or right-click): writes an indented list of the folder with sizes and modification dates to a text file. You choose the depth, whether files and hidden entries are included and whether to open the list afterwards.

## View
- **Filter** (View menu): shows only matching entries, e.g. `*.mp3`. Separate several patterns with a semicolon or comma, e.g. `*.mkv;*.mp4`. An active filter turns the path bar red.
- **Hidden files**, **single-panel view**, button bar, function key bar and toolbar can be switched in the **View** menu.
- Columns: right-click the column headers. Order and width are set directly by dragging (see [Settings](settings.md)).

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
