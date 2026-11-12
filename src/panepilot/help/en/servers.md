# FTP servers

PanePilot connects to servers via **FTP**, **FTP over TLS** (explicit or implicit) and **SFTP** (over SSH), for example your NAS or an FTP app on your phone. The server then appears in the file panel like any other folder.

## “FTP servers” sidebar
- Switch a sidebar to **FTP servers** via **View ▸ Sidebar** or by right-clicking a sidebar – left or right.
- Servers can be grouped in **folders** and rearranged with the mouse.
- **Double-click** connects. The server is shown in the file panel on the same side.
- **Right-click**:
  - on a server: connect, disconnect, edit, copy, rename, delete, new server, new folder
  - on a folder: new server, new folder, rename, delete (only if empty)
- A connected server is shown in **bold** with a **green** icon. The path bar shows the address, e.g. `sftp://alice@192.168.1.10/Download`.

## FTP server manager
**File ▸ FTP server manager …** (or “Edit …” in the context menu) – laid out like FileZilla’s:
- **General**: protocol, host and port, encryption, logon type (normal, anonymous, ask for password, key file for SFTP), user, password, background colour of the file panel and comment.
- **Advanced**: start folder on the server and a local folder for the other panel.
- **Transfer**: passive (recommended) or active – FTP only.
- **Character set**: automatic, force UTF-8 or a custom one – FTP only.

**Passwords** are stored in the system **keyring** (GNOME Keyring on GNOME), not in the settings. Without a keyring, PanePilot asks when connecting.

## Security
- **SFTP**: on the first connection PanePilot shows the server’s fingerprint. If it changes later, you get a clear warning.
- **FTP over TLS**: a self-signed certificate (e.g. from a phone app) is confirmed once and remembered.
- Plain **SCP** is not supported – almost every SSH server also offers SFTP.

## Working on the server
- **Copy/move** with F5/F6 or by dragging between the panels downloads or uploads, including whole folders. When moving, the source is only deleted after a successful transfer.
- **Rename**, **new folder** and **refresh** work as usual.
- **Delete** on a server is always **permanent** (with confirmation) – there is no trash there.
- **Double-clicking a file** downloads it to a temporary folder and opens it with the default application. Changes are not uploaded back.
- Not available on a server: search, multi-rename, meta wizard, checksums, archives, terminal and directory listing.
- The connection ends with **Disconnect**, when you switch to a local folder in the same panel (e.g. via favourites or “Back”) and when you quit. If it drops, PanePilot offers to reconnect.
- Both panels can be connected to different servers at the same time. Copying directly from server to server is not possible.

## Transfer window
Transfers run in the background – you can keep working.
- Top: files x of y, amount of data, speed, time left and a progress bar.
- Below: all files with their status (waiting, running, done, error with reason).
- Further transfers are **appended** to the queue.
- Buttons: **Pause/Resume**, **Cancel all**, **Remove selected** (waiting ones) and **Retry** (failed ones).
- With **“Close automatically after successful completion”** the window closes by itself – never when there were errors.
- If a file already exists, you get the usual question (overwrite, skip, rename, “for all”).

## Taking over from FileZilla
**Settings ▸ General ▸ FTP servers ▸ Import from FileZilla …** reads FileZilla’s server list including folders and saved passwords. Choose with the checkboxes; servers with the same name in the same folder are skipped.
