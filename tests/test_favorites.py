import json

from PySide6.QtCore import QMimeData, QModelIndex, Qt, QUrl

from panepilot.config import FAVORITES_FILE, config_dir
from panepilot.favorites import MIME_INTERNAL, FavoritesModel, FavoritesView
from panepilot.icons import IconProvider


def make_model(qapp):
    return FavoritesModel(IconProvider(), autosave=True)


def names(node):
    return [c.name for c in node.children]


def test_add_and_persist(qapp, tree):
    m = make_model(qapp)
    g = m.add_group("Projekte")
    m.add_link(str(tree / "a"), g)
    m.add_link(str(tree / "b"))
    data = json.loads((config_dir() / FAVORITES_FILE).read_text())
    assert data["items"][0]["name"] == "Projekte"
    m2 = make_model(qapp)
    m2.load()
    assert names(m2.root) == ["Projekte", "b"]
    assert m2.root.children[0].children[0].path == str(tree / "a")


def test_insertion_point_rules(qapp, tree):
    m = make_model(qapp)
    g = m.add_group("G")
    l1 = m.add_link(str(tree / "a"))
    l2 = m.add_link(str(tree / "b"))
    assert m.insertion_point(None) == (m.root, 3)          # nichts markiert → oben, ans Ende
    assert m.insertion_point(g) == (g, 0)                  # Ordner → hinein
    assert m.insertion_point(l1) == (m.root, 2)            # Favorit → direkt dahinter
    parent, row = m.insertion_point(l1)
    m.add_link(str(tree), parent, row)
    assert names(m.root) == ["G", "a", "files", "b"]
    assert l2.row() == 3


def test_move_rules(qapp, tree):
    m = make_model(qapp)
    g1 = m.add_group("G1")
    g2 = m.add_group("G2", g1)
    link = m.add_link(str(tree / "a"))
    assert m.move_node(link, g2, 0)
    assert link.parent is g2
    assert not m.move_node(g1, g2, 0)  # nicht in eigenen Unterordner
    assert m.move_node(g2, m.root, 0)
    assert names(m.root) == ["G2", "G1"]


def test_drop_urls_creates_links_only(qapp, tree):
    m = make_model(qapp)
    g = m.add_group("G")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(tree / "a")), QUrl.fromLocalFile(str(tree / "b" / "zwei.txt"))])
    assert m.dropMimeData(md, Qt.DropAction.MoveAction, -1, 0, m.index_for(g))
    assert names(g) == ["a", "zwei.txt"]
    assert (tree / "a").exists() and (tree / "b" / "zwei.txt").exists()  # Originale unberührt


def test_internal_drop_reorders(qapp, tree):
    m = make_model(qapp)
    a = m.add_link(str(tree / "a"))
    m.add_link(str(tree / "b"))
    md = m.mimeData([m.index_for(a)])
    assert md.hasFormat(MIME_INTERNAL)
    assert m.dropMimeData(md, Qt.DropAction.MoveAction, 2, 0, QModelIndex())
    assert names(m.root) == ["b", "a"]


def test_two_views_share_items_but_not_expansion(qtbot, tree):
    m = make_model(None)
    g = m.add_group("G")
    m.add_link(str(tree / "a"), g)
    left, right = FavoritesView(m), FavoritesView(m)
    qtbot.addWidget(left)
    qtbot.addWidget(right)
    left.restore_expanded([g.id])
    assert left.expanded_ids() == [g.id]
    assert right.expanded_ids() == []
    m.add_link(str(tree / "b"), g)
    assert m.rowCount(m.index_for(g)) == 2  # beide Ansichten sehen denselben Inhalt
    assert left.expanded_ids() == [g.id] and right.expanded_ids() == []


def test_missing_target_is_kept(qapp, tree):
    m = make_model(qapp)
    link = m.add_link(str(tree / "weg"))
    assert not m.target_exists(link)
    assert m.data(m.index_for(link), Qt.ItemDataRole.ForegroundRole) is not None


def test_style_persisted_and_no_auto_bold(qapp, tree):
    m = make_model(qapp)
    g = m.add_group("G")
    assert m.data(m.index_for(g), Qt.ItemDataRole.FontRole) is None  # nicht mehr automatisch fett
    link = m.add_link(str(tree / "a"), g)
    m.update_node(link, "Projekt A", str(tree / "a"), {"bold": True, "strike": True, "color": "red"})
    m2 = make_model(qapp)
    m2.load()
    n = m2.root.children[0].children[0]
    assert n.name == "Projekt A" and n.style == {"bold": True, "strike": True, "color": "red"}
    font = m2.data(m2.index_for(n), Qt.ItemDataRole.FontRole)
    assert font.bold() and font.strikeOut() and not font.italic()
    assert m2.data(m2.index_for(n), Qt.ItemDataRole.ForegroundRole).name().upper() == "#D00000"


def test_broken_link_uses_gray_and_no_entry_icon(qapp, tree):
    m = make_model(qapp)
    link = m.add_link(str(tree / "a"))
    m.update_node(link, "A", str(tree / "weg"), {"color": "red", "italic": True})
    idx = m.index_for(link)
    assert m.link_state(link) == "broken"
    assert m.data(idx, Qt.ItemDataRole.ForegroundRole).name().upper() != "#D00000"
    assert m.data(idx, Qt.ItemDataRole.FontRole).italic()
    m.update_node(link, "A", str(tree / "a"), link.style)  # repariert → eigene Farbe wieder da
    assert m.data(idx, Qt.ItemDataRole.ForegroundRole).name().upper() == "#D00000"


def test_link_in_unmounted_share_is_not_broken(qapp, tmp_path):
    from panepilot.mounts import MountManager

    share = tmp_path / "omv" / "Backup"
    share.mkdir(parents=True)
    (tmp_path / "fs").write_text(f"//omv/Backup {share} cifs rw,user,noauto 0 0\n")
    (tmp_path / "mt").write_text("")
    icons = IconProvider()
    icons.mounts = MountManager(fstab_path=str(tmp_path / "fs"), mounts_path=str(tmp_path / "mt"), poll=False)
    m = FavoritesModel(icons)
    link = m.add_link(str(share / "Steuer"))
    assert m.link_state(link) == "unmounted"
