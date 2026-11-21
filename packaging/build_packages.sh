#!/usr/bin/env bash
# Baut .deb und .rpm (x86_64) aus dem PyInstaller-Ordner dist/PanePilot (v2.0).
# Voraussetzung: packaging/build_appimage.sh ist gelaufen (dist/PanePilot existiert).
#   Aufruf: packaging/build_packages.sh
# Benötigt: dpkg-deb, rpmbuild
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(python3 -c 'import sys; sys.path.insert(0, "src"); import panepilot; print(panepilot.__version__)')"
test -x dist/PanePilot/PanePilot || { echo "dist/PanePilot fehlt – erst build_appimage.sh"; exit 1; }
ROOT="$PWD"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Gemeinsamer Inhalt: /opt/panepilot, /usr/bin/panepilot, Menüeintrag, Symbol, AppStream
stage() {  # $1 = Zielordner, $2 = Paketformat (deb/rpm)
  local dst="$1" fmt="$2"
  mkdir -p "$dst/opt" "$dst/usr/bin" "$dst/usr/share/applications" \
           "$dst/usr/share/icons/hicolor/scalable/apps" "$dst/usr/share/metainfo"
  cp -a "$ROOT/dist/PanePilot" "$dst/opt/panepilot"
  echo "$fmt" > "$dst/opt/panepilot/PACKAGE"   # Installationsart für Updates und „Über“
  cat > "$dst/usr/bin/panepilot" <<'EOF'
#!/bin/sh
exec /opt/panepilot/PanePilot "$@"
EOF
  chmod 755 "$dst/usr/bin/panepilot"
  sed 's/^Exec=.*/Exec=panepilot %U/' "$ROOT/packaging/panepilot.desktop" > "$dst/usr/share/applications/panepilot.desktop"
  cp "$ROOT/src/panepilot/icons/panepilot.svg" "$dst/usr/share/icons/hicolor/scalable/apps/panepilot.svg"
  cp "$ROOT/packaging/io.github.nea1971.panepilot.appdata.xml" "$dst/usr/share/metainfo/"
  find "$dst" -type d -exec chmod 755 {} +
}

SUMMARY="Two-panel file manager inspired by FreeCommander"
DESCRIPTION="PanePilot is a two-panel file manager with folder tree, favorites, multi-rename,
 duplicate finder, folder synchronization, FTP/SFTP and tag editing for music, photos and videos."

# --- .deb ----------------------------------------------------------------------------------------------
DEB="$WORK/deb"
stage "$DEB" deb
mkdir -p "$DEB/DEBIAN"
SIZE_KB="$(du -sk "$DEB" | cut -f1)"
cat > "$DEB/DEBIAN/control" <<EOF
Package: panepilot
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Maintainer: NEA1971 <NEA1971@users.noreply.github.com>
Homepage: https://github.com/NEA1971/PanePilot
Installed-Size: $SIZE_KB
Depends: libc6 (>= 2.35), libegl1, libgl1, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, libfontconfig1, libdbus-1-3
Recommends: ffmpeg, mkvtoolnix, libimage-exiftool-perl
Description: $SUMMARY
 $DESCRIPTION
EOF
cat > "$DEB/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
EOF
cp "$DEB/DEBIAN/postinst" "$DEB/DEBIAN/postrm"
chmod 755 "$DEB/DEBIAN/postinst" "$DEB/DEBIAN/postrm"
mkdir -p dist
dpkg-deb --root-owner-group -Zxz --build "$DEB" "dist/PanePilot-${VERSION}-amd64.deb"

# --- .rpm ----------------------------------------------------------------------------------------------
if [ "${SKIP_RPM:-}" = 1 ]; then echo "Fertig: dist/PanePilot-${VERSION}-amd64.deb (ohne .rpm)"; exit 0; fi
RPM="$WORK/rpm"
mkdir -p "$RPM"/{BUILD,RPMS,SOURCES,SPECS,SRPMS,BUILDROOT}
STAGE="$WORK/rpmroot"
stage "$STAGE" rpm
cat > "$RPM/SPECS/panepilot.spec" <<EOF
Name:           panepilot
Version:        $VERSION
Release:        1
Summary:        $SUMMARY
License:        GPL-3.0-or-later
URL:            https://github.com/NEA1971/PanePilot
BuildArch:      x86_64
AutoReqProv:    no
# Systembibliotheken für Qt – über die Dateinamen, damit es auf Fedora und openSUSE passt
Requires:       libEGL.so.1()(64bit), libGL.so.1()(64bit), libxkbcommon.so.0()(64bit), libxkbcommon-x11.so.0()(64bit)
Requires:       libxcb-cursor.so.0()(64bit), libxcb-icccm.so.4()(64bit), libxcb-keysyms.so.1()(64bit)
Requires:       libxcb-shape.so.0()(64bit), libfontconfig.so.1()(64bit), libdbus-1.so.3()(64bit)
Recommends:     /usr/bin/ffmpeg
Recommends:     /usr/bin/mkvmerge
Recommends:     /usr/bin/exiftool

%description
$(echo "$DESCRIPTION" | sed 's/^ //')

%install
mkdir -p %{buildroot}
cp -a $STAGE/. %{buildroot}/

%post
update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || :
gtk-update-icon-cache -q -t /usr/share/icons/hicolor >/dev/null 2>&1 || :

%postun
update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || :

%files
/opt/panepilot
/usr/bin/panepilot
/usr/share/applications/panepilot.desktop
/usr/share/icons/hicolor/scalable/apps/panepilot.svg
/usr/share/metainfo/io.github.nea1971.panepilot.appdata.xml
EOF
rpmbuild --define "_topdir $RPM" --define "_build_id_links none" --define "__strip /bin/true" \
  --define "debug_package %{nil}" --define "__os_install_post %{nil}" -bb "$RPM/SPECS/panepilot.spec"
cp "$RPM"/RPMS/x86_64/panepilot-"$VERSION"-1.x86_64.rpm "dist/PanePilot-${VERSION}-x86_64.rpm"
echo "Fertig: dist/PanePilot-${VERSION}-amd64.deb dist/PanePilot-${VERSION}-x86_64.rpm"
