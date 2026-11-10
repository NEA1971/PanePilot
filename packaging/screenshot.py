"""Erzeugt ein Bildschirmfoto mit Beispieldaten (für Dokumentation und Sichtprüfung)."""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main(out: str) -> None:
    base = Path(tempfile.mkdtemp(prefix="pp_demo_"))
    os.environ["PANEPILOT_CONFIG_DIR"] = str(base / "config")
    home = base / "alice"
    for d in ("Dokumente/Rechnungen", "Dokumente/Verträge", "Bilder/Urlaub 2026", "Musik", "Downloads", "Projekte/PanePilot"):
        (home / d).mkdir(parents=True, exist_ok=True)
    for f, size in (("Dokumente/Kontojournal_2026.ods", 48213), ("Dokumente/Anleitung.pdf", 1532211),
                    ("Dokumente/Notizen.txt", 2310), ("Dokumente/Budget.xlsx", 23011),
                    ("Musik/Lieblingslied.mp3", 5123311), ("Downloads/PanePilot.AppImage", 71233211)):
        p = home / f
        with open(p, "wb") as fh:
            fh.truncate(size)
    from panepilot.app import create_app

    app = create_app([])
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    m = w.fav_model
    g = m.add_group("Arbeit")
    m.add_link(str(home / "Dokumente"), g)
    m.add_link(str(home / "Projekte/PanePilot"), g)
    g2 = m.add_group("Privat")
    m.add_link(str(home / "Bilder/Urlaub 2026"), g2)
    m.add_link(str(home / "Musik"), g2)
    m.add_link(str(home / "Downloads"))
    m.add_link(str(home / "Dokumente/Kontojournal_2026.ods"))
    w.resize(1400, 760)
    w.show()
    w.sides["left"].panel.navigate(str(home / "Dokumente"))
    w.sides["right"].panel.navigate(str(home))
    w.favorites_view("left").restore_expanded([g.id, g2.id])
    w.favorites_view("right").restore_expanded([g2.id])
    w.sides["left"].panel.select_names(["Anleitung.pdf", "Notizen.txt"], current="Notizen.txt")
    w.sides["left"].panel.view.setFocus()
    w.set_active_side("left")
    app.processEvents()
    w.grab().save(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "screenshot.png")
