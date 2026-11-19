# Comparing and synchronizing folders

## Compare folders
**File → Compare folders** (Ctrl+Shift+V) compares the folder in the left window with the one in the right window and **selects** in both windows the files that only exist on that side or are newer there. Copy them (F5) to the other side. Subfolders are not searched – that is what “Synchronize folders” does.

Two files are **identical** if name, size and modification date match. Differences up to 2 seconds are ignored (USB sticks and some NAS store the time inaccurately). The options “Ignore 1 hour difference” and “Also compare content” from the synchronize dialog apply here too.

## Synchronize folders
**File → Synchronize folders …** (Ctrl+Shift+S) opens a dialog with the folders of both windows (changeable, ⇅ swaps the sides).

- **Direction:** left → right, right → left or both directions (the newer file wins). **Subfolders** are included by default.
- **Mirror:** with “delete extra items in the target”, both sides are identical afterwards: what only exists in the target goes to the **trash**, and newer files in the target are overwritten. Without the tick they stay untouched. In both directions nothing is deleted; items are copied to the other side instead.
- **Ignore 1 hour difference:** for drives that store times without a time zone.
- **Also compare content:** files with the same size and date are compared byte by byte (slow).
- **Filter:** “Only files” e.g. `*.jpg; *.png`, “Exclude” e.g. `Thumbs.db; .DS_Store; *.tmp` (also applies to folders).
- **Compare** shows a list of all differences with size and date of both sides and the planned **action**. Bold means something will happen. “Show identical files” shows the rest too.
- **Change the action:** select rows (Ctrl/Shift, Ctrl+A for all) and choose “→ to the right”, “← to the left”, “Delete right”, “Delete left” or “Do nothing” below or via right-click. Where an action does not fit a row, the row stays as it is.
- **Conflict:** if both sides have the same date but different content or size, it is unclear which one is right. Such files are set to “do nothing” – you decide.
- **Start** asks once more and then copies with progress (cancellable). A summary follows, then the folders are compared again.

## Saved synchronizations
**Save …** stores the synchronization under a name (e.g. “Photos → NAS”): both folders, all settings and the action when finished. Open it from the selection at the top of the dialog or via **File → Saved synchronizations** – it is compared at once; it starts after your review with “Start”. Saved synchronizations are part of the settings backup.

## When finished
- **Run command or script:** runs in the background without a terminal. The script gets these environment variables: `PANEPILOT_LEFT`, `PANEPILOT_RIGHT`, `PANEPILOT_RESULT` (`ok` or `errors`), `PANEPILOT_COPIED`, `PANEPILOT_DELETED`, `PANEPILOT_FAILED`, `PANEPILOT_PROFILE`. If the script reports an error (exit code other than 0), the summary shows it with the last lines of its output.
- **Suspend** or **shut down the computer:** a 30-second countdown with “Cancel” comes first.
- **When:** “only if without errors” (default) or “always”. Nothing happens after a cancel.

Server windows (FTP/SFTP) cannot be synchronized; mounted NAS shares work like local folders.
