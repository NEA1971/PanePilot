# Additional programs

Some functions use programs that PanePilot does not include because they would make it much larger. PanePilot checks whether they are installed when the function is used. If one is missing, only that function is missing; a note names the missing program.

| Program | What PanePilot uses it for | What is missing without it |
|---|---|---|
| **ffmpeg** (with ffprobe) | Measuring ReplayGain; reading duration, resolution, codecs, date taken and GPS of videos; still frame as preview; removing tracks from MP4, changing track names/“default”; MKV → MP4; repairing incomplete MKV files; duplicate search for videos | ReplayGain is greyed out; videos lack this information, MKV/AVI/MTS show almost nothing; the video functions mentioned |
| **exiftool** | Writing HEIC photos; changing or removing the date taken and GPS of MP4/MOV videos | HEIC photos read-only; for MP4/MOV the date taken and GPS are greyed out |
| **MKVToolNix** (mkvmerge, mkvextract, mkvpropedit) | Tagging MKV and WebM videos; removing, reordering and embedding tracks and subtitles in MKV; MP4/AVI/MOV → MKV; chapters in MKV | MKV/WebM read-only; these track functions |
| **7-Zip** (7z) | Packing, unpacking and writing 7z and further archive formats; encrypted ZIPs; reading RAR | these archive formats |
| **rar / unrar** (Linux only) | Unpacking RAR archives (rar can also pack) | RAR archives (on Windows 7-Zip reads RAR) |

## Installing on Linux (Debian/Ubuntu)
In a terminal: `sudo apt install ffmpeg libimage-exiftool-perl mkvtoolnix 7zip unrar`.

## Installing on Windows
- **ffmpeg:** in a command prompt `winget install Gyan.FFmpeg` – or extract the ZIP from ffmpeg.org to `C:\ffmpeg` (the programs are then in `C:\ffmpeg\bin`).
- **exiftool:** install the Windows package from exiftool.org (goes to `C:\Program Files\ExifTool`) or `winget install OliverBetz.ExifTool`.
- **MKVToolNix:** setup from mkvtoolnix.download (goes to `C:\Program Files\MKVToolNix`).
- **7-Zip:** setup from 7-zip.org (goes to `C:\Program Files\7-Zip`).

PanePilot looks in the search path (PATH) first, then in these usual folders (winget, Scoop and Chocolatey included).

## Settings → Additional programs
Shows for each program whether it was found (hover “found” to see the path), with a link to the download page. If a program is somewhere else, enter its path or pick it with **Browse …**; your own path takes precedence.

After installing, just reopen the meta wizard or the function; PanePilot does not need to be restarted. Whether ffmpeg was found is also shown under **Help → About PanePilot**.
