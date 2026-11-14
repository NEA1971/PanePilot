# Settings

Open the settings via **File ▸ Settings ▸ Settings …** or the gear button. On the left are the sections of the tab; on the right you can scroll through all of them.

## General
- **Language**: the interface language, effective after a restart.
  - **Edit …** changes texts, also for German and the other bundled languages. Only your changes are saved.
  - **New language …** creates your own language.
  - **Export …** and **Import …** exchange language files.
  - **Reset to original** removes your changes to a bundled language; **Delete language** removes your own language.
- **Backup**: PanePilot backs up its settings at the first start of each day. Here you find the location, the number to keep and the list of backups with restore, import and delete.
- **Display**: button bar, function key bar, toolbar, hidden files, single-panel view.
  - **Scaling** from 50 to 200 %, e.g. for UHD screens; takes effect after a restart.
  - **Add to application menu** (only when running as an AppImage): creates a launcher with the program icon that you can also pin to the dock. If you later start another AppImage file (e.g. a newer version), the launcher is updated automatically.
- **Updates**: if **Check for updates once a day at startup** is switched on (default: off), PanePilot asks GitHub for a new version at the first start of the day. You can check by hand at any time via **Help ▸ Check for updates …**. If there is a new version, you can download it, be reminded later or skip this version. When running as an AppImage, the new file is saved in the same folder as the running one; the old one is kept. PanePilot then asks whether to restart with the new version right away.
- **FTP servers**: **Import from FileZilla …** takes over FileZilla’s server list, see [FTP servers](servers.md).

## File view
- **Size unit**: how file sizes are shown.
- **Columns**: column profiles with visible columns and alignment; the default profile for the left and the right panel.

## Meta wizard
- **ReplayGain**: target loudness (standard −18 LUFS).

## More customising directly in the window
- **Toolbar**: right-click ▸ “Customise toolbar”, including gaps and “right-aligned from here”.
- **Function keys**: right-click the function key bar to assign keys, in four layers (none, Shift, Ctrl, Alt).
- **Keyboard shortcuts**: see [Keyboard shortcuts](shortcuts.md).

All settings are stored in the folder `~/.config/PanePilot/`.
