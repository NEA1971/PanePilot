# Comparing and synchronizing folders

## Compare folders
**File → Compare folders** (Ctrl+Shift+V) compares the folder in the left window with the one in the right window and **selects** in both windows the files that only exist on that side or are newer there. Copy them (F5) to the other side. Subfolders are not searched – that is what “Synchronize folders” does.

Two files are **identical** if name, size and modification date match. Differences up to 2 seconds are ignored (USB sticks and some NAS store the time inaccurately). The options “Ignore 1 hour difference” and “Also compare content” from the “Synchronize” sidebar apply here too.

## Synchronize folders
**File → Synchronize folders …** (Ctrl+Shift+S) switches the main window to the **comparison view**: the “Synchronize” sidebar with all settings on the left, the two folders side by side like two explorer windows (the paths at the top can be changed, ⇄ swaps the sides). The sidebar’s ✕ or “Close” button or Esc returns to the normal view.

- **Direction:** left → right, right → left or both directions (the newer file wins). **Subfolders** are included by default.
- **Mirror: target becomes exactly like the source:** afterwards both sides are identical: what only exists in the target goes to the **trash**, and newer files in the target are overwritten. Without the tick they stay untouched. In both directions nothing is deleted; items are copied to the other side instead.
- **Ignore 1 hour difference:** for drives that store times without a time zone.
- **Also compare content:** files with the same size and date are compared byte by byte (slow).
- **Filter:** “Include (files only)” e.g. `*.jpg; *.png` – folders are always searched; “Exclude (files and folders)” e.g. `Thumbs.db; .DS_Store; *.tmp; backup` – an excluded folder is left out with all its content, the name applies at any depth. Right-click a folder and choose **“Exclude folder …”** to add it here and compare again (save the synchronization to keep it).
- **Compare** shows the differences as a **tree**: name, size and date on the left and on the right, rows of both sides at the same height (if a file is missing on one side, that side of the row stays empty). Folders open and close with **+** / **−**; after comparing everything is collapsed (top level only); double-clicking a folder also expands or collapses it. Folders without differences are hidden; “Show identical files” shows the rest too.
- The **middle column** shows the symbol of the planned action per row: → or ← copy or overwrite, ✕ delete, ! conflict, – do nothing; a folder shows the action of its content, • means “mixed”. The text is in the tooltip.
- **Change the action:** select rows (Ctrl/Shift, Ctrl+A for all) and use the buttons below the middle column (→ ← ✕▸ ◂✕ –) or right-click. For a folder the action applies to everything inside; you can change single items afterwards. Where an action does not fit a row, the row stays as it is.
- **Double-click** opens the file of the clicked side with the default application.
- **Function keys** in the comparison view: F1 help, F5 synchronize, F8 delete selected rows on the right.
- **Conflict:** if both sides have the same date but different content or size, it is unclear which one is right. Such files are set to “do nothing” – you decide.
- **Synchronize** (button, F5 or right-click into the empty area of the list, where “Compare” is offered too) asks once more and then copies with progress (cancellable). A summary follows, then the folders are compared again.

## Saved synchronizations
**Save …** stores the synchronization under a name (e.g. “Photos → NAS”): both folders, all settings and the action when finished. Open it from the selection at the top of the sidebar or via **File → Saved synchronizations** – it is compared at once; it is synchronized after your review with “Synchronize”. Saved synchronizations are part of the settings backup.

## FreeFileSync
- **FreeFileSync → Import from FreeFileSync …** imports `.ffs_gui` and `.ffs_batch` files (several at once) as saved synchronizations; the name is the file name. If it exists, PanePilot asks.
- Imported are the folder pair (one synchronization per pair), direction, mirroring, content comparison, filters and the command after synchronizing. “Update” becomes “left → right” without mirroring, “Mirror” becomes “left → right” with mirroring, real two-way synchronizations become “both directions”.
- The FFS database `*.ffs_db` is added to “Exclude” automatically. What cannot be imported (e.g. versioning, size and time filters, paths in filters, change detection via the FFS database) is listed in the report after the import.
- **Export to FreeFileSync …** saves the current synchronization as `.ffs_gui`, **Export all …** all saved ones into a folder. “Ignore 1 hour” is not written to the file; add it in FreeFileSync if needed.

## When finished
- **Run command or script:** runs in the background without a terminal. The script gets these environment variables: `PANEPILOT_LEFT`, `PANEPILOT_RIGHT`, `PANEPILOT_RESULT` (`ok` or `errors`), `PANEPILOT_COPIED`, `PANEPILOT_DELETED`, `PANEPILOT_FAILED`, `PANEPILOT_PROFILE`. If the script reports an error (exit code other than 0), the summary shows it with the last lines of its output.
- **Suspend** or **shut down the computer:** a 30-second countdown with “Cancel” comes first.
- **When:** “only if without errors” (default) or “always”. Nothing happens after a cancel.

Server windows (FTP/SFTP) cannot be synchronized; mounted NAS shares work like local folders.
