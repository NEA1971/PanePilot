"""Abgleiche aus FreeFileSync übernehmen und nach FreeFileSync schreiben (v1.17, L-1700 ff.)."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from . import folderdiff as fd
from . import syncprofiles as sp
from .i18n import t

EXTENSIONS = (".ffs_gui", ".ffs_batch")
XML_FORMAT = "23"


# --- Filter --------------------------------------------------------------------------------------------------
def _from_ffs_pattern(item: str) -> tuple[str, bool]:
    """FFS-Muster → Namensmuster; zweiter Wert: verkürzt (es hatte einen Pfad)."""
    p = (item or "").strip().replace("\\", "/")
    if not p:
        return "", False
    p = p.rstrip("/")
    while p.startswith("*/"):
        p = p[2:]
    anchored = p.startswith("/")
    p = p.lstrip("/")
    shortened = anchored or "/" in p
    if "/" in p:
        p = p.rsplit("/", 1)[-1]
    return p, shortened


def _to_ffs_pattern(name: str) -> str:
    return name if name == "*" else "*/" + name


# --- Import --------------------------------------------------------------------------------------------------
def _direction(sync: ET.Element | None) -> tuple[str, bool, list[str]]:
    """Richtung, Spiegeln und Hinweise aus <Synchronize>."""
    notes: list[str] = []
    if sync is None:
        return fd.LR, False, notes
    variant = (sync.findtext("Variant") or "").strip().lower()
    diff = sync.find("Differences")
    custom = sync.find("CustomDirections")
    changes = sync.find("Changes")
    if changes is not None:  # Änderungserkennung per Datenbank, z. B. „Aktualisieren“ oder „Zwei-Wege“
        lc, rc = changes.find("Left"), changes.find("Right")

        def vals(node):
            return {k: ((node.get(k) if node is not None else None) or "none").lower()
                    for k in ("Create", "Update", "Delete")}

        lv, rv = vals(lc), vals(rc)
        if set(rv.values()) == {"none"} and lv["Create"] == lv["Update"] == "right":
            return fd.LR, lv["Delete"] == "right", notes  # Änderungen links → rechts
        if set(lv.values()) == {"none"} and rv["Create"] == rv["Update"] == "left":
            return fd.RL, rv["Delete"] == "left", notes
        notes.append(t("ffs.note_database"))
        return fd.BOTH, False, notes
    if variant == "twoway":
        notes.append(t("ffs.note_database"))
        return fd.BOTH, False, notes
    if variant == "mirror":
        return fd.LR, True, notes
    if variant == "update":
        return fd.LR, False, notes
    values: dict[str, str] = {}
    if diff is not None:
        values = {k: (diff.get(k) or "none").lower() for k in ("LeftOnly", "LeftNewer", "RightNewer", "RightOnly")}
    elif custom is not None:
        values = {k: (custom.findtext(k) or "none").strip().lower()
                  for k in ("LeftOnly", "LeftNewer", "RightNewer", "RightOnly")}
    if not values:
        return fd.LR, False, notes
    vals = set(values.values())
    if "left" not in vals:  # alles nach rechts (oder nichts)
        mirror = values["RightOnly"] == "right"
        expected = {"LeftOnly": "right", "LeftNewer": "right", "RightNewer": "right" if mirror else "none",
                    "RightOnly": "right" if mirror else "none"}
        if values != expected:
            notes.append(t("ffs.note_directions"))
        return fd.LR, mirror, notes
    if "right" not in vals:
        mirror = values["LeftOnly"] == "left"
        expected = {"RightOnly": "left", "RightNewer": "left", "LeftNewer": "left" if mirror else "none",
                    "LeftOnly": "left" if mirror else "none"}
        if values != expected:
            notes.append(t("ffs.note_directions"))
        return fd.RL, mirror, notes
    if values != {"LeftOnly": "right", "LeftNewer": "right", "RightNewer": "left", "RightOnly": "left"}:
        notes.append(t("ffs.note_directions"))
    return fd.BOTH, False, notes


def _filters(filt: ET.Element | None) -> tuple[str, str, list[str]]:
    notes: list[str] = []
    if filt is None:
        return "*", "", notes
    inc, exc = [], []
    for tag, out in (("Include", inc), ("Exclude", exc)):
        node = filt.find(tag)
        items = [i.text or "" for i in node.findall("Item")] if node is not None else []
        if node is not None and not items and (node.text or "").strip():  # alte Form: eine Zeile mit „|“/„;“
            items = [x for x in (node.text or "").replace("|", ";").replace("\n", ";").split(";")]
        for item in items:
            raw = item.strip()
            if not raw:
                continue
            if tag == "Include" and raw.replace("\\", "/").endswith("/"):  # Ordner einschließen: geht nicht
                notes.append(t("ffs.note_include_folder", item=raw))
                continue
            name, short = _from_ffs_pattern(raw)
            if not name:
                continue
            if short and name != "*":
                notes.append(t("ffs.note_path_filter", item=raw, name=name))
            if name not in out:
                out.append(name)
    for tag in ("SizeMin", "SizeMax", "TimeSpan"):
        node = filt.find(tag)
        if node is not None and (node.text or "0").strip() not in ("", "0"):
            notes.append(t("ffs.note_size_time"))
            break
    include = "; ".join(inc) if inc and inc != ["*"] else "*"
    return include, "; ".join(exc), notes


def parse(path: str) -> tuple[list[sp.Profile], list[str]]:
    """Eine FFS-Datei → Abgleiche (je Ordnerpaar einer) und Hinweise (L-1702, L-1703)."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ValueError(str(exc)) from exc
    if root.tag != "FreeFileSync":
        raise ValueError(t("ffs.not_ffs"))
    notes: list[str] = []
    compare = root.find("Compare")
    variant = (compare.findtext("Variant") if compare is not None else "") or "TimeAndSize"
    content = variant.strip().lower() == "content"
    if variant.strip().lower() == "size":
        notes.append(t("ffs.note_size_only"))
    dst = False
    shift = (compare.findtext("IgnoreTimeShift") if compare is not None else "") or ""
    if shift.strip():
        parts = [p.strip() for p in shift.replace(";", ",").split(",") if p.strip()]
        if parts in (["1"], ["1:00"], ["60"]):
            dst = True
        else:
            notes.append(t("ffs.note_timeshift", value=shift.strip()))
    sync = root.find("Synchronize")
    direction, mirror, n = _direction(sync)
    notes += n
    policy = ((sync.findtext("DeletionPolicy") if sync is not None else "") or "RecycleBin").strip()
    if policy != "RecycleBin" and (mirror or direction != fd.BOTH):
        notes.append(t("ffs.note_deletion", policy=policy))
    include, exclude, n = _filters(root.find("Filter"))
    notes += n
    after = sp.After()
    cmd = root.find("PostSyncCommand")
    if cmd is not None and (cmd.text or "").strip():
        cond = (cmd.get("Condition") or "Completion").strip()
        when = sp.WHEN_OK if cond == "Success" else sp.WHEN_ALWAYS
        if cond == "Errors":
            notes.append(t("ffs.note_errors_only"))
        after = sp.After(sp.AFTER_COMMAND, cmd.text.strip(), when)
    opts = fd.Options(direction, True, dst, content, mirror, include, exclude)
    base = os.path.splitext(os.path.basename(path))[0]
    pairs = root.findall("FolderPairs/Pair")
    out = []
    for i, pair in enumerate(pairs, 1):
        left, right = (pair.findtext("Left") or "").strip(), (pair.findtext("Right") or "").strip()
        if not left or not right:
            continue
        if any(pair.find(x) is not None for x in ("Compare", "Synchronize", "Filter")):
            notes.append(t("ffs.note_pair_settings"))
        if any(":" in p.split("/")[0] and not p.startswith("/") for p in (left, right)):
            notes.append(t("ffs.note_not_local", path=left if not left.startswith("/") else right))
        name = base if len(pairs) == 1 or i == 1 else f"{base} ({i})"
        out.append(sp.Profile(name, left, right, fd.Options(**opts.to_dict()), sp.After(**after.to_dict())))
    if len(pairs) > 1:
        notes.append(t("ffs.note_pairs", n=len(pairs)))
    seen, unique = set(), []
    for x in notes:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return out, unique


# --- Export (L-1710 ff.) -------------------------------------------------------------------------------------
def to_xml(p: sp.Profile) -> str:
    o = p.options
    root = ET.Element("FreeFileSync", {"XmlType": "GUI", "XmlFormat": XML_FORMAT})
    ET.SubElement(root, "Notes")
    comp = ET.SubElement(root, "Compare")
    ET.SubElement(comp, "Variant").text = "Content" if o.content else "TimeAndSize"
    ET.SubElement(comp, "Symlinks").text = "Exclude"
    ET.SubElement(comp, "IgnoreTimeShift")  # bleibt leer (Sommerzeit ggf. in FFS nachtragen)
    sync = ET.SubElement(root, "Synchronize")
    if o.direction == fd.BOTH:
        d = {"LeftOnly": "right", "LeftNewer": "right", "RightNewer": "left", "RightOnly": "left"}
    elif o.direction == fd.LR:
        d = {"LeftOnly": "right", "LeftNewer": "right", "RightNewer": "right" if o.mirror else "none",
             "RightOnly": "right" if o.mirror else "none"}
    else:
        d = {"LeftOnly": "left" if o.mirror else "none", "LeftNewer": "left" if o.mirror else "none",
             "RightNewer": "left", "RightOnly": "left"}
    ET.SubElement(sync, "Differences", d)
    ET.SubElement(sync, "DeletionPolicy").text = "RecycleBin"
    ET.SubElement(sync, "VersioningFolder", {"Style": "Replace"})
    filt = ET.SubElement(root, "Filter")
    inc = ET.SubElement(filt, "Include")
    for name in fd.patterns(o.include) or ["*"]:
        ET.SubElement(inc, "Item").text = _to_ffs_pattern(name)
    exc = ET.SubElement(filt, "Exclude")
    for name in fd.patterns(o.exclude):
        ET.SubElement(exc, "Item").text = _to_ffs_pattern(name)
    ET.SubElement(filt, "SizeMin", {"Unit": "None"}).text = "0"
    ET.SubElement(filt, "SizeMax", {"Unit": "None"}).text = "0"
    ET.SubElement(filt, "TimeSpan", {"Type": "None"}).text = "0"
    pairs = ET.SubElement(root, "FolderPairs")
    pair = ET.SubElement(pairs, "Pair")
    ET.SubElement(pair, "Left").text = p.left
    ET.SubElement(pair, "Right").text = p.right
    ET.SubElement(root, "Errors", {"Ignore": "false", "Retry": "0", "Delay": "5"})
    cmd = ET.SubElement(root, "PostSyncCommand",
                        {"Condition": "Success" if p.after.when == sp.WHEN_OK else "Completion"})
    if p.after.kind == sp.AFTER_COMMAND and p.after.command.strip():
        cmd.text = p.after.command.strip()
    ET.SubElement(root, "LogFolder")
    ET.SubElement(root, "EmailNotification", {"Condition": "Always"})
    ET.SubElement(root, "GridViewType").text = "Action"
    ET.indent(root, space="    ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def export_notes(p: sp.Profile) -> list[str]:
    notes = []
    if p.options.dst:
        notes.append(t("ffs.export_dst"))
    if p.after.kind in (sp.AFTER_SUSPEND, sp.AFTER_SHUTDOWN):
        notes.append(t("ffs.export_power"))
    return notes


def safe_file_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad or ord(c) < 32 else c for c in name).strip(" .")
    return out or "PanePilot"


def save(p: sp.Profile, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(to_xml(p))
