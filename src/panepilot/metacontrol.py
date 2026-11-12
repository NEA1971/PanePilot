"""Steuerung des Meta-Wizards im Hauptfenster (F-900 ff.) – als Mixin, damit mainwindow.py überschaubar bleibt."""

from __future__ import annotations

import os

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from .dialogs import ErrorListDialog, _msgbox, show_error
from .i18n import t

MODE_META = "meta"
META_ALLOWED = {"quit", "about", "help", "help_online", "check_updates", "donate"}  # während des Meta-Wizards erlaubte Funktionen


class MetaWizardMixin:
    meta_mode = None  # dict mit dem vorherigen Zustand, solange der Meta-Wizard läuft

    # --- Aufbau ------------------------------------------------------------------------------------
    def _make_meta_pane(self, _side: str):
        from .metawizard import MetaModel, MetaPane, MetaView

        pane = MetaPane()
        pane.meta_model = MetaModel(pane)
        pane.meta_view = MetaView(pane.meta_model)
        pane.close_clicked.connect(self.meta_close)
        pane.save_clicked.connect(lambda: self.meta_save())
        pane.discard_clicked.connect(self.meta_discard)
        pane.undo_clicked.connect(self.meta_undo)
        pane.stop_clicked.connect(self._meta_stop_scan)
        pane.field_committed.connect(self._meta_field_committed)
        pane.cover_replace.connect(self._meta_cover_replace)
        pane.cover_remove.connect(self._meta_cover_remove)
        pane.cover_save.connect(self._meta_cover_save)
        pane.layout_changed.connect(self._meta_save_layout)
        pane.meta_view.layout_changed.connect(self._meta_save_layout)
        pane.meta_view.escape_pressed.connect(self.meta_close)
        pane.meta_view.selectionModel().selectionChanged.connect(lambda *_: self._meta_selection_changed())
        pane.meta_view.field_editor_requested.connect(self.meta_field_editor)
        from . import convert as cv
        from .replaygain import ffmpeg_path

        if not ffmpeg_path():  # ReplayGain braucht ffmpeg (v0.9.6)
            btn = pane.convert_buttons[cv.REPLAYGAIN]
            btn.setEnabled(False)
            btn.setToolTip(t("rg.needs_ffmpeg"))
        pane.meta_view.row_menu_requested.connect(self._meta_row_menu)
        pane.convert_requested.connect(self.meta_convert)
        pane.long_text_requested.connect(self._meta_long_text)
        return pane

    def _meta_pane(self):
        side = self.meta_mode["side"] if self.meta_mode is not None else self.active_side
        return self.sides[side].sidebar.widget_for(MODE_META)

    # --- Öffnen (F-900, F-901) ---------------------------------------------------------------------
    def do_meta_wizard(self, paths: list[str] | None = None) -> None:
        if self.meta_mode is not None or self.rename_mode is not None:
            return
        panel = self.active
        if panel.in_trash or panel.search_mode:
            return
        from .metawizard import MetaScanThread

        if paths is None:
            marked = [e for e in panel.selected_entries() if not e.is_parent]
            paths = [e.path for e in marked] or [panel.current_path]
        side = self.active_side
        s = self.sides[side]
        for other in list(self.tool_mode):
            self.close_tool(other)
        self.meta_mode = {"side": side, "single": self.single_mode, "sidebar": s.sidebar.mode,
                          "inner": s.splitter.sizes(), "scan": None, "save": None, "undo": None, "rg": None}
        if not self.single_mode:
            self.set_single_mode(True)
        s.sidebar.set_mode(MODE_META)
        pane = self._meta_pane()
        view = pane.meta_view
        pane.meta_model.beginResetModel()
        pane.meta_model.items = []
        pane.meta_model.endResetModel()
        pane.meta_model.custom_fields = [n for n in (self.settings.get("meta_custom_fields") or [])
                                         if isinstance(n, str)]
        pane.extra_keys = pane.meta_model.extra_keys()
        pane.set_layout(self.settings.get("meta_sidebar") or [])
        view.restore_layout(self.settings.get("meta_layout") or {})
        total = sum(s.splitter.sizes())
        s.splitter.setSizes([400, max(total - 400, 200)])
        s.panel.set_custom_view(view)
        # Gesperrte Funktionen ausgrauen (wie beim Umbenennen)
        self._meta_disabled = [aid for aid, act in self.qactions.items()
                               if act.isEnabled() and aid not in META_ALLOWED]
        for aid in self._meta_disabled:
            self.qactions[aid].setEnabled(False)
        self.fkey_bar.setEnabled(False)
        if getattr(self, "_meta_save_shortcut", None) is None:
            self._meta_save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
            self._meta_save_shortcut.activated.connect(lambda: self.meta_mode is not None and self.meta_save())
        self._meta_save_shortcut.setEnabled(True)
        # Einlesen im Hintergrund (F-904); weitere Freigaben unterhalb nicht betreten (F-905)
        base = panel.current_path
        exclude = {mp for mp in self.mounts.network_mount_points()
                   if not any(os.path.normpath(p) == mp or os.path.normpath(p).startswith(mp + os.sep) for p in paths)}
        thread = MetaScanThread(paths, bool(self.settings.get("show_hidden")), panel.model.accept, exclude, self)
        thread.found.connect(lambda recs, b=base: self._meta_found(recs, b))
        thread.progress.connect(self._meta_progress)
        thread.finished_scan.connect(self._meta_scan_done)
        self.meta_mode["scan"] = thread
        self.meta_mode["base"] = base
        self._meta_update_state()
        pane.summary.setText(t("meta.collecting", n=0))
        thread.start()
        view.setFocus()

    def _meta_found(self, records, base: str) -> None:
        if self.meta_mode is None:
            return
        from .metawizard import MetaItem

        pane = self._meta_pane()
        # Keine automatische Markierung: ohne Markierung gelten Export, Nummerieren usw. für alle Titel
        pane.meta_model.add_items([MetaItem(r, base) for r in records])

    def _meta_progress(self, done: int, total: int) -> None:
        if self.meta_mode is None:
            return
        pane = self._meta_pane()
        if total < 0:
            pane.summary.setText(t("meta.collecting", n=done))
        else:
            pane.summary.setText(t("meta.reading", done=done, total=total))

    def _meta_scan_done(self, complete: bool) -> None:
        if self.meta_mode is None:
            return
        self.meta_mode["scan"] = None
        pane = self._meta_pane()
        items = pane.meta_model.items
        errors = sum(1 for it in items if it.record.error)
        text = t("meta.loaded" if complete else "meta.stopped", n=len(items))
        if errors:
            text += " " + t("meta.read_errors", n=errors)
        if not items:
            text = t("meta.none_found")
        pane.summary.setText(text)
        pane.extra_keys = pane.meta_model.extra_keys()
        self._meta_update_state()

    def _meta_stop_scan(self) -> None:
        if self.meta_mode is None:
            return
        for key in ("scan", "rg"):
            if self.meta_mode.get(key) is not None:
                self.meta_mode[key].stop()

    def _meta_update_state(self) -> None:
        if self.meta_mode is None:
            return
        pane = self._meta_pane()
        pane.update_state(scanning=self.meta_mode.get("scan") is not None or self.meta_mode.get("rg") is not None,
                          saving=self.meta_mode.get("save") is not None,
                          has_changes=bool(pane.meta_model.changed_items()),
                          can_undo=bool(self.meta_mode.get("undo")))

    # --- Bearbeiten (F-921 ff.) ---------------------------------------------------------------------
    def _meta_selection_changed(self) -> None:
        if self.meta_mode is None:
            return
        pane = self._meta_pane()
        pane.show_selection(pane.meta_view.selected_items())

    def _meta_apply(self, change) -> None:
        pane = self._meta_pane()
        items = pane.meta_view.selected_items()
        for it in items:
            if not it.record.error:
                change(it)
        pane.meta_model.rows_changed()
        pane.show_selection(items)
        self._meta_update_state()

    def _meta_field_committed(self, key: str, value) -> None:
        if self.meta_mode is None or self.meta_mode.get("save") is not None:
            return
        self._meta_apply(lambda it: it.readonly(key) or it.set(key, value))

    def _meta_cover_replace(self, pic) -> None:
        from .metawizard import replace_front

        pane = self._meta_pane()
        single = len(pane.meta_view.selected_items()) == 1
        index = pane.cover.index if single and pane.cover.pictures else None
        self._meta_apply(lambda it: it.set_pictures(replace_front(it.pictures(), pic, index)))

    def _meta_cover_remove(self, index: int) -> None:
        from .metawizard import remove_shown

        pane = self._meta_pane()
        single = len(pane.meta_view.selected_items()) == 1
        self._meta_apply(lambda it: it.set_pictures(remove_shown(it.pictures(), index if single and index >= 0 else None)))

    def _meta_cover_save(self, pic) -> None:
        pane = self._meta_pane()
        items = pane.meta_view.selected_items()
        if pic is None or not items:
            return
        ext = ".png" if pic.mime == "image/png" else ".jpg"
        start = os.path.join(os.path.dirname(items[0].record.path), "cover" + ext)
        path, _f = QFileDialog.getSaveFileName(self, t("meta.cover_save"), start,
                                               t("meta.cover_filter") + f" (*{ext})")
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(pic.data)
        except OSError as exc:
            show_error(self, t("meta.cover_save"), f"{path}: {exc.strerror or exc}")

    # --- Speichern, Verwerfen, Rückgängig (F-925, F-943, F-944) ---------------------------------------
    def meta_save(self, after=None) -> None:
        if self.meta_mode is None or self.meta_mode.get("save") is not None or self.meta_mode.get("rg") is not None:
            return
        from .metawizard import SaveJob

        pane = self._meta_pane()
        items = pane.meta_model.changed_items()
        if not items:
            if after:
                after()
            return
        jobs = [SaveJob(it.record, dict(it.pending), it.pending_pictures, it.pending_name) for it in items]
        self._meta_run_jobs(jobs, True, after)

    def meta_undo(self) -> None:
        if self.meta_mode is None or not self.meta_mode.get("undo") or self.meta_mode.get("save") is not None:
            return
        jobs = list(self.meta_mode["undo"])
        self.meta_mode["undo"] = None
        self._meta_run_jobs(jobs, False, None)

    def _meta_run_jobs(self, jobs, saving: bool, after) -> None:
        from .metawizard import MetaSaveThread

        pane = self._meta_pane()
        by_path = {it.record.path: it for it in pane.meta_model.items}
        errors: list[tuple[str, str]] = []
        undo_jobs: list = []
        done: list[str] = []
        thread = MetaSaveThread(jobs, self)

        def saved(path, rec, undo):
            it = by_path.get(path)
            if it is None:
                return
            if saving:  # Änderungen stehen jetzt in der Datei
                it.pending = {}
                it.pending_pictures = None
                it.pending_name = None
                it.mark = ""
            it.record = rec
            # nach „Rückgängig“ bleiben noch nicht gespeicherte Änderungen erhalten, soweit noch nötig
            it.pending = {k: v for k, v in it.pending.items()
                          if (v or None) != (rec.fields.get(k) or None) or (v is None and k in rec.data)}
            if it.pending_name == rec.name:
                it.pending_name = None
            if undo is not None:
                undo_jobs.append(undo)
            done.append(path)

        def failed(path, reason):
            errors.append((os.path.basename(path), reason))

        def progress(n, total):
            pane.summary.setText(t("meta.saving", done=n, total=total))

        def finished():
            self.meta_mode["save"] = None
            if saving:
                self.meta_mode["undo"] = undo_jobs or None
                pane.summary.setText(t("meta.saved", n=len(done)))
            else:
                pane.summary.setText(t("meta.undone", n=len(done)))
            pane.meta_model.rows_changed()
            pane.extra_keys = pane.meta_model.extra_keys()
            pane.show_selection(pane.meta_view.selected_items())
            self._meta_update_state()
            if errors:
                ErrorListDialog(self, t("meta.title"), t("meta.save_errors"), errors).exec()
            elif after:
                after()

        thread.saved.connect(saved)
        thread.failed.connect(failed)
        thread.progress.connect(progress)
        thread.finished.connect(finished)
        self.meta_mode["save"] = thread
        self._meta_update_state()
        thread.start()

    def meta_discard(self) -> None:
        if self.meta_mode is None or self.meta_mode.get("save") is not None:
            return
        pane = self._meta_pane()
        for it in pane.meta_model.items:
            it.pending = {}
            it.pending_pictures = None
            it.pending_name = None
            it.mark = ""
        pane.meta_model.rows_changed()
        pane.show_selection(pane.meta_view.selected_items())
        self._meta_update_state()

    # --- Langer Text (F-980) ----------------------------------------------------------------------------
    def _meta_long_text(self, key: str) -> None:
        from .metadialogs import TextDialog
        from .metawizard import column_title

        pane = self._meta_pane()
        items = pane.meta_view.selected_items()
        if not items or self.meta_mode.get("save") is not None:
            return
        values = {it.value(key) for it in items}
        dlg = TextDialog(self, column_title(key), values.pop() if len(values) == 1 else "")
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._meta_field_committed(key, dlg.text() or None)

    # --- Kontextmenü der Titelzeilen (F-990) ---------------------------------------------------------------
    def _meta_row_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        from . import convert as cv

        if self.meta_mode is None:
            return
        pane = self._meta_pane()
        busy = self.meta_mode.get("save") is not None
        has = bool(pane.meta_view.selected_items())
        menu = QMenu(self)
        has_any = bool(pane.meta_model.items)
        for kind in cv.TOOLS:
            if kind == cv.TAG_TO_TEXT:
                menu.addSeparator()
            act = menu.addAction(t(f"conv.{kind}"))
            enabled = (has if kind in cv.KINDS else has_any) and not busy and self.meta_mode.get("rg") is None
            if kind == cv.REPLAYGAIN:
                from .replaygain import ffmpeg_path

                enabled = enabled and bool(ffmpeg_path())
            act.setEnabled(enabled)
            act.triggered.connect(lambda _c=False, k=kind: self.meta_convert(k))
        menu.exec(pos)

    # --- Feld-Editor (F-970 ff.) ---------------------------------------------------------------------------
    def meta_field_editor(self) -> None:
        if self.meta_mode is None or self.meta_mode.get("save") is not None:
            return
        from . import tags as tg
        from .metadialogs import FieldEditorDialog, collect_fields

        pane = self._meta_pane()
        model = pane.meta_model
        items = [it for it in model.items if not it.record.error]
        rows = collect_fields(items, model.custom_fields)
        dlg = FieldEditorDialog(self, rows, len(items))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        custom = list(model.custom_fields)

        def matches(it, row):
            if row.kind == "data":
                return [k for k, label in it.record.data.items() if label.casefold() == row.label.casefold()]
            if row.key.startswith(tg.EXTRA):
                k = tg.find_key(it.record, row.key)
                return [k] if k else []
            return [row.key] if row.key in it.record.fields or row.key in it.pending else []

        for row in dlg.deletions():
            for it in items:
                for k in matches(it, row):
                    it.set(k, None)
            custom = [c for c in custom if c.casefold() != row.label.casefold()]
        for row, new_name in dlg.renames():
            for it in items:
                for k in matches(it, row):
                    value = it.value(k)
                    it.set(k, None)
                    if value:
                        it.set(tg.custom_key(it.record.kind, new_name), value)
            custom = [new_name if c.casefold() == row.label.casefold() else c for c in custom]
            self._meta_rename_column(tg.EXTRA + row.label, tg.EXTRA + new_name)
        for name in dlg.new_fields():
            if name.casefold() not in {c.casefold() for c in custom}:
                custom.append(name)
        model.custom_fields = custom
        self.settings.set("meta_custom_fields", custom)
        pane.extra_keys = model.extra_keys()
        model.rows_changed()
        pane.show_selection(pane.meta_view.selected_items())
        self._meta_update_state()

    def _meta_rename_column(self, old: str, new: str) -> None:
        """Umbenanntes Feld in Spalten und Seitenleiste mitnehmen."""
        pane = self._meta_pane()
        cols = pane.meta_model.columns
        oldf = old.casefold()
        if any(c.casefold() == oldf for c in cols):
            pane.meta_view.set_columns([new if c.casefold() == oldf else c for c in cols])
        if any(k.casefold() == oldf for k in pane.layout_keys):
            pane._apply([new if k.casefold() == oldf else k for k in pane.layout_keys])

    # --- Konverter (F-990 ff.) ---------------------------------------------------------------------------
    def _meta_presets(self, kind: str) -> list[dict]:
        from . import convert as cv

        stored = self.settings.get("meta_presets") or {}
        presets = stored.get(kind) if isinstance(stored, dict) else None
        if not isinstance(presets, list):
            presets = cv.DEFAULT_PRESETS[kind]
        return [p for p in presets if isinstance(p, dict) and isinstance(p.get("format"), str)]

    @staticmethod
    def _meta_getter(it):
        from . import tags as tg

        def get(name: str) -> str:
            if name == "_filename":
                return os.path.splitext(it.display_name)[0]
            if name == "_folder":
                return os.path.basename(os.path.dirname(it.record.path))
            if name in tg.FIELDS:
                return it.value(name)
            return it.value(tg.EXTRA + name)

        return get

    def _meta_target(self, field_name: str) -> str:
        from . import tags as tg

        return field_name if field_name in tg.FIELDS else tg.EXTRA + field_name

    def _meta_compute(self, kind: str, fmt: str, field: str, items):
        """Ergebnis je Titel: (Titel, Werte bzw. Name oder None, Fehler)."""
        from . import convert as cv

        results = []
        if kind == cv.TAG_TO_FILE:
            targets: dict[tuple[str, str], int] = {}
            for it in items:
                try:
                    name = cv.safe_filename(cv.evaluate(fmt, self._meta_getter(it)))
                except cv.FormatError as exc:
                    raise exc
                ext = os.path.splitext(it.record.name)[1]
                if not name:
                    results.append((it, None, t("rename.err_empty")))
                    continue
                new = name + ext
                key = (os.path.dirname(it.record.path), new)
                targets[key] = targets.get(key, 0) + 1
                results.append((it, new, ""))
            checked = []
            for it, new, err in results:
                if new and not err:
                    folder = os.path.dirname(it.record.path)
                    if targets[(folder, new)] > 1:
                        err = t("rename.err_duplicate", name=new)
                    elif new != it.record.name and os.path.exists(os.path.join(folder, new)):
                        err = t("rename.err_exists", name=new)
                checked.append((it, new, err))
            return checked
        if kind == cv.FILE_TO_TAG:
            cv.compile_pattern(fmt)  # Formatfehler sofort melden
            for it in items:
                values = cv.parse_filename(os.path.splitext(it.display_name)[0], fmt)
                results.append((it, values, "" if values is not None else t("conv.no_match")))
            return results
        for it in items:  # Tag → Tag
            results.append((it, cv.evaluate(fmt, self._meta_getter(it)), ""))
        return results

    def meta_convert(self, kind: str) -> None:
        if self.meta_mode is None or self.meta_mode.get("save") is not None:
            return
        from . import convert as cv
        from . import tags as tg
        from .metadialogs import ConverterDialog
        from .metawizard import column_title

        if kind not in cv.KINDS:
            if self.meta_mode is None or self.meta_mode.get("rg") is not None:
                return
            {cv.TAG_TO_TEXT: self.meta_export_text, cv.TEXT_TO_TAG: self.meta_import_text,
             cv.NUMBER: self.meta_number, cv.DISC: self.meta_disc, cv.MUSICBRAINZ: self.meta_musicbrainz,
             cv.PLAYLIST: self.meta_playlist, cv.REPLAYGAIN: self.meta_replaygain}[kind]()
            return
        pane = self._meta_pane()
        items = [it for it in pane.meta_view.selected_items() if not it.record.error]
        if not items:
            return
        model = pane.meta_model
        extra_labels = list(model.extra_keys().values())
        last = (self.settings.get("meta_last_format") or {}).get(kind, "")

        def preview(fmt: str, field: str):
            # (OK erlaubt, Text, Warnung): ein unpassender erster Titel sperrt OK nicht, Formatfehler schon
            if not fmt.strip():
                return False, "", False
            try:
                if kind == cv.FILE_TO_TAG:
                    bad = [n for n in cv.pattern_fields(fmt) if n.startswith("_")]
                    if bad:
                        raise cv.FormatError(", ".join(f"%{n}%" for n in bad))
                res = self._meta_compute(kind, fmt, field, items[:1])
            except cv.FormatError as exc:
                return False, t("conv.format_error", reason=str(exc)), True
            it, value, err = res[0]
            if err:
                return True, f"{it.display_name}: {err}", True
            if kind == cv.TAG_TO_FILE:
                return True, value, False
            if kind == cv.FILE_TO_TAG:
                return True, "\n".join(f"{column_title(self._meta_target(n))}: {v}" for n, v in value.items()), False
            return True, value or t("conv.empty_removes"), False

        fields = [(k, column_title(k)) for k in tg.FIELDS] + [(k, label) for k, label in model.extra_keys().items()]
        last_field = (self.settings.get("meta_last_format") or {}).get("tag2tag_field", "title")
        dlg = ConverterDialog(self, kind, self._meta_presets(kind), last, extra_labels, preview, fields, last_field)
        accepted = dlg.exec() == dlg.DialogCode.Accepted
        stored = dict(self.settings.get("meta_presets") or {})
        stored[kind] = dlg.presets
        self.settings.set("meta_presets", stored)
        if not accepted:
            return
        fmt, field = dlg.format_string(), dlg.field()
        lastmap = dict(self.settings.get("meta_last_format") or {})
        lastmap[kind] = fmt
        if kind == cv.TAG_TO_TAG:
            lastmap["tag2tag_field"] = field
        self.settings.set("meta_last_format", lastmap)
        try:
            results = self._meta_compute(kind, fmt, field, items)
        except cv.FormatError as exc:
            show_error(self, t(f"conv.{kind}"), t("conv.format_error", reason=str(exc)))
            return
        for it, value, err in results:
            it.mark = err
            if err:
                continue
            if kind == cv.TAG_TO_FILE:
                it.pending_name = None if value == it.record.name else value
            elif kind == cv.FILE_TO_TAG:
                for name, v in value.items():
                    if not name.startswith("_"):
                        it.set(self._meta_target(name), v or None)
            else:
                it.set(field, value or None)
        marked = sum(1 for _it, _v, err in results if err)
        if marked:
            pane.summary.setText(t("conv.marked", n=marked))
        model.rows_changed()
        pane.show_selection(pane.meta_view.selected_items())
        self._meta_update_state()

    # --- v0.9.3: Export, Import, Nummerieren, Playlist ------------------------------------------------------
    def _meta_targets(self):
        pane = self._meta_pane()
        return [it for it in pane.meta_view.target_items() if not it.record.error]

    def _meta_refresh(self) -> None:
        pane = self._meta_pane()
        pane.meta_model.rows_changed()
        pane.show_selection(pane.meta_view.selected_items())
        self._meta_update_state()

    def meta_export_text(self) -> None:
        from .metaextras import export_table, next_export_name, write_table

        items = self._meta_targets()
        if not items:
            return
        pane = self._meta_pane()
        folder = self.meta_mode.get("base") or os.path.dirname(items[0].record.path)
        start = os.path.join(folder, next_export_name(folder) + ".txt")
        txt, csvf = t("textexp.filter_txt") + " (*.txt)", t("textexp.filter_csv") + " (*.csv)"
        path, chosen = QFileDialog.getSaveFileName(self, t("conv.tag2text"), start, f"{txt};;{csvf}")
        if not path:
            return
        ext = ".csv" if chosen == csvf else ".txt"
        if not path.lower().endswith((".txt", ".csv")):
            path += ext
        header, rows = export_table(items, pane.meta_model.columns, pane.meta_model)
        try:
            write_table(path, header, rows)
        except OSError as exc:
            show_error(self, t("conv.tag2text"), f"{path}: {exc.strerror or exc}")
            return
        pane.summary.setText(t("textexp.done", n=len(rows), name=os.path.basename(path)))

    def meta_import_text(self) -> None:
        from .metaextras import ImportDialog, read_text_file

        items = self._meta_targets()
        if not items:
            return
        pane = self._meta_pane()
        folder = self.meta_mode.get("base") or os.path.dirname(items[0].record.path)
        path, _f = QFileDialog.getOpenFileName(self, t("conv.text2tag"), folder,
                                               t("textimp.filter") + " (*.txt *.csv);;* (*)")
        if not path:
            return
        labels = list(pane.meta_model.extra_keys().values())
        try:
            data = read_text_file(path, labels)
        except OSError as exc:
            show_error(self, t("conv.text2tag"), f"{path}: {exc.strerror or exc}")
            return
        if not data.rows:
            show_error(self, t("conv.text2tag"), t("textimp.empty"))
            return
        from . import convert as cv
        from .metadialogs import placeholder_menu

        last = (self.settings.get("meta_last_format") or {}).get(cv.TEXT_TO_TAG, "")
        dlg = ImportDialog(self, items, data, self._meta_presets(cv.TEXT_TO_TAG), last,
                           lambda edit, button: placeholder_menu(dlg, cv.FILE_TO_TAG, labels, edit, button))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        if data.header is None:
            lastmap = dict(self.settings.get("meta_last_format") or {})
            lastmap[cv.TEXT_TO_TAG] = dlg.format_string()
            self.settings.set("meta_last_format", lastmap)
        try:
            pairs = dlg.pairs()
        except cv.FormatError as exc:
            show_error(self, t("conv.text2tag"), t("conv.format_error", reason=str(exc)))
            return
        marked = 0
        for it, values in pairs:
            if values is None:
                it.mark = t("conv.no_match")
                marked += 1
                continue
            it.mark = ""
            for key, value in values.items():
                if not it.readonly(key):
                    it.set(key, value)
        pane.summary.setText(t("conv.marked", n=marked) if marked else t("textimp.done", n=len(pairs) - marked))
        self._meta_refresh()

    def meta_number(self) -> None:
        from .metaextras import NumberDialog

        items = self._meta_targets()
        if not items:
            return
        dlg = NumberDialog(self, len(items), self.settings.get("meta_number") or {})
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.settings.set("meta_number", dlg.settings())
        for it, value in zip(items, dlg.values()):
            it.set("track", value)
        self._meta_refresh()

    # --- v1.2: Disc-Assistent und MusicBrainz -------------------------------------------------------------
    def meta_disc(self) -> None:
        from .metaextras import DiscDialog

        items = self._meta_targets()
        if not items:
            return
        dlg = DiscDialog(self, items, self.settings.get("meta_disc") or {})
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.settings.set("meta_disc", dlg.settings())
        for it, values in dlg.changes():
            for key, value in values.items():
                if not it.readonly(key):
                    it.set(key, value)
        self._meta_refresh()

    def meta_musicbrainz(self) -> None:
        from . import musicbrainz as mb
        from . import netutil
        from . import tags as tg
        from .mbdialogs import ApplyDialog, ResultsDialog, SearchDialog, cover_mime

        items = self._meta_targets()
        if not items:
            return
        title = t("mb.title")
        album, artist = mb.search_terms(items)
        while True:
            sdlg = SearchDialog(self, album, artist, len(items))
            if sdlg.exec() != sdlg.DialogCode.Accepted:
                return
            album, artist = sdlg.terms()
            hits, error = netutil.run_blocking(self, lambda: mb.search(album, artist), t("mb.searching"), title)
            if error:
                show_error(self, title, t("mb.failed", reason=error))
                continue
            if hits is None:
                continue
            rdlg = ResultsDialog(self, hits, len(items))
            res = rdlg.exec()
            if res == ResultsDialog.BACK:
                continue
            if res != QDialog.DialogCode.Accepted or rdlg.selected() is None:
                return
            hit = rdlg.selected()
            loaded, error = netutil.run_blocking(self, lambda: mb.load_release(hit.id), t("mb.loading"), title)
            if error:
                show_error(self, title, t("mb.failed", reason=error))
                continue
            if loaded is None:
                continue
            release, cover = loaded
            adlg = ApplyDialog(self, release, cover, items, self.settings.get("meta_musicbrainz") or {})
            if adlg.exec() != QDialog.DialogCode.Accepted:
                return
            break
        self.settings.set("meta_musicbrainz", adlg.settings())
        cover_data = adlg.cover_data()
        changes = adlg.changes()
        for it, values in changes:
            it.mark = ""
            for fid, value in values.items():
                key = mb.FIELD_BY_ID[fid].key(it.record.kind)
                if not it.readonly(key):
                    it.set(key, value)
            if cover_data:
                others = [p for p in it.pictures() if p.ptype != tg.FRONT_COVER]
                it.set_pictures([tg.Picture(cover_data, cover_mime(cover_data), tg.FRONT_COVER, "")] + others)
        self._meta_pane().summary.setText(t("mb.done", n=len(changes)))
        self._meta_refresh()

    def meta_playlist(self) -> None:
        from .dialogs import confirm
        from .metaextras import PlaylistDialog, default_playlist_path, write_playlist

        items = self._meta_targets()
        if not items:
            return
        relative = self.settings.get("meta_playlist_relative")
        dlg = PlaylistDialog(self, default_playlist_path(items), True if relative is None else bool(relative),
                             len(items))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.settings.set("meta_playlist_relative", dlg.relative.isChecked())
        path = dlg.target()
        if not path:
            return
        if os.path.exists(path) and not confirm(self, t("playlist.title"),
                                                t("playlist.overwrite", name=os.path.basename(path))):
            return
        try:
            write_playlist(path, items, dlg.relative.isChecked())
        except OSError as exc:
            show_error(self, t("playlist.title"), f"{path}: {exc.strerror or exc}")
            return
        self._meta_pane().summary.setText(t("playlist.done", n=len(items), name=os.path.basename(path)))

    # --- ReplayGain (v0.9.6) -------------------------------------------------------------------------------
    def meta_replaygain(self) -> None:
        from . import replaygain as rg
        from .metaextras import ReplayGainDialog
        from .metawizard import ReplayGainThread

        if not rg.ffmpeg_path():
            show_error(self, t("conv.replaygain"), t("rg.needs_ffmpeg"))
            return
        items = self._meta_targets()
        if not items:
            return
        try:
            target = float(self.settings.get("replaygain_target"))
        except (TypeError, ValueError):
            target = rg.DEFAULT_TARGET
        groups: dict[str, list] = {}
        for it in items:
            album = it.value("album").strip()
            if album:
                groups.setdefault(album.casefold(), []).append(it)
        dlg = ReplayGainDialog(self, len(items), len(groups), target, bool(self.settings.get("replaygain_overwrite")))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        overwrite = dlg.overwrite.isChecked()
        self.settings.set("replaygain_overwrite", overwrite)

        def missing(it, album: bool) -> bool:
            if it.record.codec == "Opus":
                keys = [rg.R128_ALBUM] if album else [rg.R128_TRACK]
            else:
                keys = [rg.ALBUM_GAIN, rg.ALBUM_PEAK] if album else [rg.TRACK_GAIN, rg.TRACK_PEAK]
            return any(not it.value(tg_extra(k)) for k in keys)

        from . import tags as tgm

        def tg_extra(name: str) -> str:
            return tgm.EXTRA + name

        todo = []
        for it in items:
            needs = overwrite or missing(it, False)
            group = groups.get(it.value("album").strip().casefold())
            if group is not None and (overwrite or any(missing(g, True) for g in group)):
                needs = True  # für die Album-Lautheit wird jeder Titel des Albums gemessen
            if needs:
                todo.append(it)
        pane = self._meta_pane()
        if not todo:
            pane.summary.setText(t("rg.nothing"))
            return
        results: dict[str, object] = {}
        errors: list[tuple[str, str]] = []
        thread = ReplayGainThread([it.record.path for it in todo], self)
        thread.measured.connect(lambda path, m: results.__setitem__(path, m))
        thread.failed.connect(lambda path, reason: errors.append((os.path.basename(path), reason)))
        thread.progress.connect(lambda n, total: pane.summary.setText(t("rg.progress", done=n, total=total)))

        def finished():
            stopped = thread._stop
            self.meta_mode["rg"] = None
            changed = 0
            for it in todo:
                m = results.get(it.record.path)
                if m is None:
                    continue
                group = groups.get(it.value("album").strip().casefold())
                album_loud = album_peak = None
                if group is not None and all(g.record.path in results for g in group):
                    album_loud, album_peak = rg.album_values([results[g.record.path] for g in group])
                for name, value in rg.tag_values(it.record.codec, m, album_loud, album_peak, target).items():
                    if overwrite or not it.value(tg_extra(name)):
                        it.set(tg_extra(name), value)
                if it.changed:
                    changed += 1
            text = t("rg.done", n=len(results), changed=changed)
            if stopped:
                text = t("rg.stopped", n=len(results))
            pane.summary.setText(text)
            pane.extra_keys = pane.meta_model.extra_keys()
            self._meta_refresh()
            if errors:
                ErrorListDialog(self, t("conv.replaygain"), t("rg.errors"), errors).exec()

        thread.finished.connect(finished)
        self.meta_mode["rg"] = thread
        self._meta_update_state()
        pane.summary.setText(t("rg.progress", done=0, total=len(todo)))
        thread.start()

    # --- Schließen ---------------------------------------------------------------------------------------
    def meta_close(self, then=None) -> bool:
        """Schließen mit Rückfrage bei ungespeicherten Änderungen (F-925). False = abgebrochen."""
        if self.meta_mode is None:
            return True
        if self.meta_mode.get("save") is not None:
            return False
        pane = self._meta_pane()
        changed = pane.meta_model.changed_items()
        if changed:
            answer = _msgbox(self, QMessageBox.Icon.Question, t("meta.title"), t("meta.unsaved", n=len(changed)), [
                ("meta.save", QMessageBox.ButtonRole.AcceptRole, True),
                ("meta.discard_close", QMessageBox.ButtonRole.DestructiveRole, False),
                ("button.cancel", QMessageBox.ButtonRole.RejectRole, False),
            ])
            if answer == "meta.save":
                self.meta_save(after=lambda: (self.leave_meta_mode(), then() if then else None))
                return False
            if answer != "meta.discard_close":
                return False
        self.leave_meta_mode()
        return True

    def leave_meta_mode(self) -> None:
        state = self.meta_mode
        if state is None:
            return
        for key in ("scan", "rg"):
            worker = state.get(key)
            if worker is not None:
                worker.stop()
                worker.wait(10000)
        save = state.get("save")
        if save is not None:
            save.wait()
        self._meta_save_layout()
        s = self.sides[state["side"]]
        self.meta_mode = None
        s.panel.set_custom_view(None)
        s.sidebar.set_mode(state["sidebar"])
        for aid in getattr(self, "_meta_disabled", []):
            self.qactions[aid].setEnabled(True)
        self._meta_disabled = []
        self.fkey_bar.setEnabled(True)
        if getattr(self, "_meta_save_shortcut", None) is not None:
            self._meta_save_shortcut.setEnabled(False)
        if not state["single"]:
            self.set_single_mode(False)
        QApplication.processEvents()
        s.splitter.setSizes(state["inner"])
        s.panel.refresh()
        self._update_nav_actions()
        s.panel.view.setFocus()

    def _meta_save_layout(self) -> None:
        side = self.meta_mode["side"] if self.meta_mode is not None else None
        pane = self.sides[side].sidebar.widget_for(MODE_META) if side else None
        if pane is None:
            return
        self.settings.set("meta_layout", pane.meta_view.layout_state())
        self.settings.set("meta_sidebar", list(pane.layout_keys))

    def meta_selected_paths(self) -> list[str]:
        if self.meta_mode is None:
            return []
        return [it.record.path for it in self._meta_pane().meta_view.selected_items()]

