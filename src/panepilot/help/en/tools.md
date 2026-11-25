# Additional programs

Some functions use programs that are not included in the AppImage because they would make it much larger. PanePilot checks whether they are installed when the function is used. If one is missing, only that function is missing; a note then shows the command. On Debian and Ubuntu, install them in a terminal with `sudo apt install …`.

| Program | What PanePilot uses it for | What is missing without it | Install |
|---|---|---|---|
| **ffmpeg** | Measuring ReplayGain; reading duration, resolution, codecs, date taken and GPS of videos; still frame as preview | ReplayGain is greyed out; videos lack this information, MKV/AVI/MTS show almost nothing | `sudo apt install ffmpeg` |
| **exiftool** | Writing HEIC photos; changing or removing the date taken and GPS of MP4/MOV videos | HEIC photos read-only; for MP4/MOV the date taken and GPS are greyed out | `sudo apt install libimage-exiftool-perl` |
| **mkvpropedit, mkvextract** (package mkvtoolnix) | Tagging MKV and WebM videos | MKV/WebM read-only | `sudo apt install mkvtoolnix` |
| **7-Zip** (7z) | Packing and unpacking 7z and further archive formats | these archive formats | `sudo apt install 7zip` |
| **rar / unrar** | Unpacking RAR archives (rar can also pack) | RAR archives | `sudo apt install unrar` or `rar` |

After installing, just reopen the meta wizard or the function; PanePilot does not need to be restarted. Whether ffmpeg was found is also shown under **Help → About PanePilot**.
