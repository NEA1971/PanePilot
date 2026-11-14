#!/usr/bin/env bash
# Baut PanePilot als AppImage (x86_64).
#   Aufruf: packaging/build_appimage.sh <pfad-zu-appimagetool> [ausgabedatei]
set -euo pipefail
cd "$(dirname "$0")/.."
APPIMAGETOOL="${1:?Pfad zu appimagetool fehlt}"
VERSION="$(python3 -c 'import sys; sys.path.insert(0, "src"); import panepilot; print(panepilot.__version__)')"
OUT="${2:-dist/PanePilot-${VERSION}-x86_64.AppImage}"

rm -rf build dist/PanePilot AppDir
# Build-Datum für „Über PanePilot“ (v0.9.11); die Datei steht in .gitignore
echo "BUILD_DATE = \"$(date -u +%Y-%m-%d)\"" > src/panepilot/_build.py
python3 -m PyInstaller --noconfirm --clean --onedir --windowed \
  --name PanePilot \
  --paths src \
  --add-data "src/panepilot/i18n/*.json:panepilot/i18n" \
  --add-data "src/panepilot/icons:panepilot/icons" \
  --add-data "src/panepilot/help:panepilot/help" \
  --exclude-module tkinter \
  --exclude-module pytest \
  packaging/launcher.py

mkdir -p AppDir/usr/lib AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/scalable/apps AppDir/usr/share/metainfo
cp -a dist/PanePilot AppDir/usr/lib/panepilot
cp packaging/AppRun AppDir/AppRun
cp packaging/panepilot.desktop AppDir/panepilot.desktop
cp packaging/panepilot.desktop AppDir/usr/share/applications/panepilot.desktop
cp src/panepilot/icons/panepilot.svg AppDir/panepilot.svg
cp src/panepilot/icons/panepilot.svg AppDir/usr/share/icons/hicolor/scalable/apps/panepilot.svg
ln -sf panepilot.svg AppDir/.DirIcon
cp packaging/io.github.nea1971.panepilot.appdata.xml AppDir/usr/share/metainfo/

mkdir -p "$(dirname "$OUT")"
# Update-Angabe (v1.1): AppImageUpdate / Gear Lever finden neue Versionen über die GitHub-Releases
# und laden mit der .zsync-Datei nur die Änderungen.
UPDATE_INFO="gh-releases-zsync|NEA1971|PanePilot|latest|PanePilot-*x86_64.AppImage.zsync"
ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run -u "$UPDATE_INFO" AppDir "$OUT"
if [ ! -f "$OUT.zsync" ] && command -v zsyncmake >/dev/null; then
  (cd "$(dirname "$OUT")" && zsyncmake "$(basename "$OUT")")
fi
echo "Fertig: $OUT"
