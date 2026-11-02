# -*- coding: utf-8 -*-
"""Native Global Workspace management for Parts Manager PLM / FreeCAD 1.1.

The optional global workspace API is separate from local Workspace.py.
"""
from urllib.parse import urljoin
import os
import re
from parts_manager_plm import PlmDownload
from parts_manager_plm import WorkspaceInventory
from parts_manager_plm import PlmTags
import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets
from parts_manager_plm.GlobalWorkspaceApi import GlobalWorkspaceApi

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")


class GlobalWorkspacePanel(QtWidgets.QWidget):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.api = GlobalWorkspaceApi(connection)
        self.workspaces = []
        self.current_workspace = None
        self.current_inventory = None
        self._synced_part_paths = {}
        self._build_ui()
        self.refresh_workspaces()

    def _button(self, text, callback, layout):
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _icon_button(self, filename, tooltip, callback, layout):
        button = QtWidgets.QPushButton()
        path = os.path.join(ICON_DIR, filename)
        if os.path.isfile(path):
            button.setIcon(QtGui.QIcon(path))
        else:
            button.setText({'import.svg': '+', 'sync.svg': 'Sync',
                            'remove.svg': '-', 'open.svg': 'Open',
                            'checkout.svg': 'Out', 'checkin.svg': 'In',
                            'tags.svg': 'Tags', 'approve.svg': 'OK',
                             'share.svg': 'Share', 'browser.svg': 'Web'}.get(filename, '?'))
        button.setIconSize(QtCore.QSize(28, 28))
        button.setFixedSize(42, 42)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel('Global Workspace:'))
        self.workspace_combo = QtWidgets.QComboBox()
        self.workspace_combo.setMinimumWidth(230)
        self.workspace_combo.currentIndexChanged.connect(self.refresh_inventory)
        top.addWidget(self.workspace_combo, 1)
        self._button('Refresh', self.refresh_workspaces, top)
        self._button('Create', self.create_workspace, top)
        self.duplicate_button = self._button('Duplicate', self.duplicate_workspace, top)
        self.delete_button = self._button('Delete', self.delete_workspace, top)
        layout.addLayout(top)

        self.details = QtWidgets.QLabel('Select a global workspace.')
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.parts_table = QtWidgets.QTableWidget()
        self.parts_table.setColumnCount(5)
        self.parts_table.setHorizontalHeaderLabels([
            'Part', 'Workspace Version', 'Latest CAD Version', 'Update Available', 'Local Status'])
        self.parts_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.parts_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.parts_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.parts_table.setAlternatingRowColors(True)
        header = self.parts_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(self.parts_table, 1)

        # Match the Local Workspace icon toolbar and its order.
        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(6)
        self.add_button = self._icon_button('import.svg', 'Search / Add PLM Parts', self.add_part, actions)
        self.sync_button = self._icon_button('sync.svg', 'Sync global workspace to computer', self.sync_workspace, actions)
        self.remove_button = self._icon_button('remove.svg', 'Remove selected parts from global workspace', self.remove_parts, actions)
        self.open_button = self._icon_button('open.svg', 'Open selected parts in FreeCAD', self.open_parts, actions)
        self.checkout_button = self._icon_button('checkout.svg', 'Check out selected PLM parts', self.checkout_parts, actions)
        self.checkin_button = self._icon_button('checkin.svg', 'Check in selected parts to PLM', self.checkin_parts, actions)
        self.tags_button = self._icon_button('tags.svg', 'Edit tags of selected PLM parts', self.edit_tags, actions)
        actions.addStretch()
        self.approve_button = self._icon_button('approve.svg', 'Approve latest CAD version and update local copy', self.approve_versions, actions)
        self.members_button = self._icon_button('share.svg', 'Manage global workspace members', self.manage_members, actions)
        self.manager_button = self._icon_button('browser.svg', 'Open global workspace in browser', self.open_manager, actions)
        layout.addLayout(actions)
        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._update_permissions()

    def _workspace_id(self):
        return self.workspace_combo.currentData()

    def _role(self):
        return str((self.current_workspace or {}).get('role', '')).upper()

    def _update_permissions(self):
        w = self.current_workspace or {}
        selected = self._workspace_id() is not None
        can_edit = selected and bool(w.get('canEdit', self._role() in ('OWNER', 'EDITOR')))
        owner = selected and bool(w.get('canManageMembers', self._role() == 'OWNER'))
        for button in (self.add_button, self.remove_button, self.approve_button, self.tags_button):
            button.setEnabled(can_edit)
        self.members_button.setEnabled(owner)
        self.delete_button.setEnabled(owner)
        self.duplicate_button.setEnabled(selected)
        self.sync_button.setEnabled(selected)
        self.open_button.setEnabled(selected)
        self.checkout_button.setEnabled(selected)
        self.checkin_button.setEnabled(selected)

    def _error(self, operation, exc):
        self.status.setText('{}: {}'.format(operation, exc))
        QtWidgets.QMessageBox.warning(self, 'Global Workspaces', '{}:\n{}'.format(operation, exc))

    def _selected_parts(self):
        selected = []
        for row in sorted(set(index.row() for index in self.parts_table.selectionModel().selectedRows())):
            item = self.parts_table.item(row, 0)
            if item:
                selected.append((item.text(), item.data(QtCore.Qt.UserRole)))
        return selected

    def _revision(self):
        if not self.current_inventory:
            raise ValueError('Workspace inventory is not loaded.')
        return int(self.current_inventory['inventoryRevision'])

    def set_connection(self, connection):
        self.connection = connection
        self.api = GlobalWorkspaceApi(connection)
        self.refresh_workspaces()

    def refresh_workspaces(self, preferred_id=None):
        try:
            previous_id = preferred_id if preferred_id is not None else self._workspace_id()
            self.workspaces = self.api.list_workspaces()
            self.workspace_combo.blockSignals(True)
            self.workspace_combo.clear()
            for w in self.workspaces:
                if isinstance(w, dict) and w.get('id') is not None:
                    self.workspace_combo.addItem(str(w.get('name') or 'Unnamed Workspace'), w['id'])
            index = self.workspace_combo.findData(previous_id)
            if index >= 0:
                self.workspace_combo.setCurrentIndex(index)
            self.workspace_combo.blockSignals(False)
            self.refresh_inventory()
        except Exception as exc:
            self.current_workspace = None
            self.current_inventory = None
            self.parts_table.setRowCount(0)
            self.details.setText('Global workspaces unavailable.')
            self._update_permissions()
            self.status.setText('Could not load global workspaces: {}'.format(exc))

    def refresh_inventory(self, *_):
        self.parts_table.setRowCount(0)
        self.current_workspace = None
        self.current_inventory = None
        workspace_id = self._workspace_id()
        if workspace_id is None:
            self.details.setText('No accessible global workspaces.')
            self._update_permissions()
            return
        try:
            payload = self.api.inventory(workspace_id)
            self.current_workspace = payload.get('workspace') or {}
            self.current_inventory = payload['inventory']
            w = self.current_workspace
            inv = self.current_inventory
            self.details.setText('Owner: {}    Access: {}    Inventory revision: {}\n{}'.format(
                w.get('owner', ''), w.get('role', ''), inv.get('inventoryRevision', ''),
                w.get('description', '') or ''))
            parts = inv.get('parts', {})
            entries = sorted((p for p in parts.values() if isinstance(p, dict)),
                             key=lambda p: str(p.get('name', '')).lower())
            self.parts_table.setRowCount(len(entries))
            for row, part in enumerate(entries):
                values = [part.get('name') or part.get('file') or '',
                          part.get('version', ''), part.get('latestVersion', ''),
                          'Yes' if part.get('updateAvailable') else 'No',
                          self._local_status(part)]
                for column, value in enumerate(values):
                    item = QtWidgets.QTableWidgetItem('' if value is None else str(value))
                    if column == 0:
                        item.setData(QtCore.Qt.UserRole, part.get('partId'))
                    self.parts_table.setItem(row, column, item)
            self.status.setText('{} part(s) in global workspace.'.format(len(entries)))
        except Exception as exc:
            self.details.setText('Could not load workspace inventory.')
            self.status.setText(str(exc))
        finally:
            self._update_permissions()

    def _local_status(self, part):
        """Compare the downloaded file and its local workspace.json with server CAD version."""
        part_id = part.get('partId')
        directory = self._sync_directory()
        if not directory:
            return 'Not configured'
        path = self._local_path(part_id)
        if not path or not os.path.isfile(path):
            return 'Not downloaded'
        local = WorkspaceInventory.get_workspace_part(directory, part_id) or {}
        local_version = local.get('cadVersion') or local.get('version')
        latest_version = part.get('latestVersion')
        if not local_version or not latest_version:
            return 'Downloaded (version unknown)'
        if str(local_version) == str(latest_version):
            return 'Up to date'
        return 'Outdated (local {})'.format(local_version)

    def create_workspace(self):
        name, ok = QtWidgets.QInputDialog.getText(self, 'Create Global Workspace', 'Workspace name:')
        if not ok or not name.strip():
            return
        description, ok = QtWidgets.QInputDialog.getMultiLineText(
            self, 'Create Global Workspace', 'Description (optional):')
        if not ok:
            return
        try:
            result = self.api.create(name.strip(), description)
            self.refresh_workspaces((result.get('workspace') or {}).get('id'))
        except Exception as exc:
            self._error('Create workspace failed', exc)

    def duplicate_workspace(self):
        workspace_id = self._workspace_id()
        if workspace_id is None:
            return
        original = self.workspace_combo.currentText()
        name, ok = QtWidgets.QInputDialog.getText(
            self, 'Duplicate Global Workspace', 'Name for copy:', text=original + ' Copy')
        if not ok or not name.strip():
            return
        try:
            result = self.api.duplicate(workspace_id, name.strip())
            self.refresh_workspaces((result.get('workspace') or {}).get('id'))
        except Exception as exc:
            self._error('Duplicate workspace failed', exc)

    def delete_workspace(self):
        workspace_id = self._workspace_id()
        if workspace_id is None:
            return
        name = self.workspace_combo.currentText()
        answer = QtWidgets.QMessageBox.question(self, 'Delete Global Workspace',
            'Permanently delete global workspace "{}"?\n\nThis cannot be undone.'.format(name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        if answer != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.api.delete(workspace_id)
            self.refresh_workspaces()
        except Exception as exc:
            self._error('Delete workspace failed', exc)

    def add_part(self):
        workspace_id = self._workspace_id()
        if workspace_id is None:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Search PLM Parts')
        dialog.resize(780, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        search_row = QtWidgets.QHBoxLayout()
        query = QtWidgets.QLineEdit()
        query.setPlaceholderText('Enter at least 2 characters of a part name')
        search_row.addWidget(query, 1)
        search_button = QtWidgets.QPushButton('Search')
        search_row.addWidget(search_button)
        layout.addLayout(search_row)
        table = QtWidgets.QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(['Part Name', 'Label', 'CAD Version'])
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(table)
        message = QtWidgets.QLabel('Search for parts to add to this global workspace.')
        layout.addWidget(message)
        footer = QtWidgets.QHBoxLayout()
        add_button = QtWidgets.QPushButton('Add Selected Parts')
        add_button.setEnabled(False)
        footer.addWidget(add_button)
        footer.addStretch()
        close_button = QtWidgets.QPushButton('Close')
        close_button.clicked.connect(dialog.reject)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        def search():
            term = query.text().strip()
            if len(term) < 2:
                message.setText('Enter at least two characters.')
                return
            search_button.setEnabled(False)
            try:
                results = self.api.search_parts(term)
                table.setRowCount(len(results))
                for row, part in enumerate(results):
                    name = part.get('originalName') or ''
                    label = part.get('label') or ''
                    version = part.get('version') or part.get('computedVersion') or ''
                    for col, value in enumerate((name, label, version)):
                        item = QtWidgets.QTableWidgetItem(str(value))
                        if col == 0:
                            item.setData(QtCore.Qt.UserRole, part.get('id'))
                        table.setItem(row, col, item)
                message.setText('{} matching PLM part(s). Select rows to add.'.format(len(results)))
                add_button.setEnabled(bool(results))
            except Exception as exc:
                message.setText('Search failed: {}'.format(exc))
            finally:
                search_button.setEnabled(True)

        def add_selected():
            rows = sorted(set(i.row() for i in table.selectionModel().selectedRows()))
            if not rows:
                message.setText('Select one or more parts.')
                return
            existing = set(str(p.get('partId')) for p in
                           (self.current_inventory or {}).get('parts', {}).values())
            added, skipped, failures = 0, 0, []
            add_button.setEnabled(False)
            try:
                for row in rows:
                    item = table.item(row, 0)
                    if item is None:
                        continue
                    part_id = item.data(QtCore.Qt.UserRole)
                    if part_id is None:
                        failures.append('{}: missing part ID'.format(item.text()))
                        continue
                    if str(part_id) in existing:
                        skipped += 1
                        continue
                    try:
                        response = self.api.add_part(workspace_id, part_id, self._revision())
                        self.current_inventory = (response.get('inventory')
                            if isinstance(response.get('inventory'), dict)
                            else self.api.inventory(workspace_id)['inventory'])
                        existing.add(str(part_id))
                        added += 1
                    except Exception as exc:
                        failures.append('{}: {}'.format(item.text(), exc))
                        break  # Revision may be stale; do not continue.
            finally:
                add_button.setEnabled(True)
                self.refresh_inventory()
            message.setText('Added: {}. Already present: {}.{}'.format(
                added, skipped, (' Errors: ' + '; '.join(failures)) if failures else ''))

        search_button.clicked.connect(search)
        query.returnPressed.connect(search)
        add_button.clicked.connect(add_selected)
        dialog.exec_()

    @staticmethod
    def _download_filename(part):
        """Resolve inventory names, including PLM names without .FCStd.

        The existing PlmDownload downloader reads and extracts the archive;
        Global Workspace supplies the intended destination filename.
        """
        for field in ('originalName', 'file', 'name'):
            value = part.get(field)
            if not value:
                continue
            name = os.path.basename(str(value).strip().replace('\\', '/'))
            if not name or name in ('.', '..'):
                continue
            if re.fullmatch(r'plm_part_\d+(?:\.fcstd)?', name, re.IGNORECASE):
                continue
            if name.lower().endswith('.fcstd'):
                return name
            # PLM originalName commonly contains the CAD stem only.
            # Reject other explicit extensions rather than treating a PDF,
            # ZIP, etc. as a FreeCAD document.
            if not os.path.splitext(name)[1]:
                return name + '.FCStd'
        return None

    def sync_workspace(self):
        """Download global inventory to a separate local folder, without altering local workspaces."""
        workspace_id = self._workspace_id()
        if workspace_id is None:
            return
        try:
            inventory = self.api.inventory(workspace_id)['inventory']
            parts = sorted(inventory.get('parts', {}).values(),
                           key=lambda p: str(p.get('name', '')).lower())
        except Exception as exc:
            self._error('Load global workspace inventory failed', exc)
            return
        if not parts:
            QtWidgets.QMessageBox.information(self, 'Sync Global Workspace', 'This workspace has no parts.')
            return
        settings = QtCore.QSettings('PMPLM', 'PartsManager')
        key = 'globalWorkspaceDirectory/{}'.format(workspace_id)
        previous = str(settings.value(key, '') or '')
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Select Local Folder for Global Workspace', previous or os.path.expanduser('~'))
        if not directory:
            return
        directory = os.path.realpath(directory)
        settings.setValue(key, directory)
        settings.sync()
        existing = []
        targets = []
        errors = []
        used_names = {}
        for part in parts:
            filename = self._download_filename(part)
            if not filename:
                errors.append('Part {}: no usable original CAD filename (originalName={!r}, file={!r}, name={!r})'.format(
                    part.get('partId'), part.get('originalName'), part.get('file'), part.get('name')))
                continue
            name_key = filename.casefold()
            if name_key in used_names:
                errors.append('Part {}: filename {} conflicts with part {}. Skipped to avoid overwriting.'.format(
                    part.get('partId'), filename, used_names[name_key]))
                continue
            used_names[name_key] = part.get('partId')
            target = os.path.realpath(os.path.join(directory, filename))
            if os.path.commonpath((directory, target)) != directory:
                errors.append('Part {}: unsafe filename {}'.format(part.get('partId'), filename))
                continue
            targets.append((part, target))
            if os.path.exists(target):
                existing.append(filename)
        overwrite = False
        if existing:
            answer = QtWidgets.QMessageBox.question(
                self, 'Sync Global Workspace',
                '{} file(s) already exist in the selected folder.\n\n'
                'Yes: overwrite existing files (except open modified documents).\n'
                'No: download only missing files.\nCancel: stop.'.format(len(existing)),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.No)
            if answer == QtWidgets.QMessageBox.Cancel:
                return
            overwrite = answer == QtWidgets.QMessageBox.Yes
        downloaded = skipped = 0
        self.sync_button.setEnabled(False)
        progress = QtWidgets.QProgressDialog('Downloading global workspace parts...', 'Cancel',
                                             0, len(targets), self)
        progress.setWindowModality(QtCore.Qt.WindowModal)
        try:
            for index, (part, target) in enumerate(targets):
                progress.setValue(index)
                QtWidgets.QApplication.processEvents()
                if progress.wasCanceled():
                    break
                name = os.path.basename(target)
                if os.path.exists(target) and not overwrite:
                    skipped += 1
                    continue
                if any(os.path.normcase(os.path.realpath(getattr(doc, 'FileName', '') or '.'))
                       == os.path.normcase(target) and getattr(doc, 'Modified', False)
                       for doc in __import__('FreeCAD').listDocuments().values()):
                    skipped += 1
                    errors.append('{}: open with unsaved changes'.format(name))
                    continue
                try:
                    result = PlmDownload.download_part(
                        connection=self.connection, part_id=part['partId'],
                        part_data={'originalName': name, 'name': name,
                                   'file': name,
                                   'version': part.get('latestVersion')},
                        workspace=directory, force=True,
                        destination_path=target)
                    if result and os.path.isfile(result):
                        self._synced_part_paths[str(part['partId'])] = os.path.realpath(result)
                        downloaded += 1
                        if os.path.basename(result) != name:
                            FreeCAD.Console.PrintMessage(
                                'PLM: Archive filename for part {} is {} (inventory: {})\n'.format(
                                    part['partId'], os.path.basename(result), name))
                    else:
                        errors.append('{}: download failed'.format(name))
                except Exception as exc:
                    errors.append('{}: {}'.format(name, exc))
        finally:
            progress.setValue(len(targets))
            self.sync_button.setEnabled(True)
        summary = 'Downloaded: {}. Skipped: {}. Failed: {}.\nFolder: {}'.format(
            downloaded, skipped, len(errors), directory)
        if errors:
            summary += '\n\n' + '\n'.join(errors[:20])
        self.status.setText(summary)
        self.refresh_inventory()
        self.status.setText(summary)
        if errors:
            QtWidgets.QMessageBox.warning(self, 'Global Workspace Sync', summary)
        else:
            QtWidgets.QMessageBox.information(self, 'Global Workspace Sync', summary)

    def _sync_directory(self):
        wid = self._workspace_id()
        settings = QtCore.QSettings('PMPLM', 'PartsManager')
        path = str(settings.value('globalWorkspaceDirectory/{}'.format(wid), '') or '')
        return os.path.realpath(path) if path and os.path.isdir(path) else None

    def _part_record(self, part_id):
        for part in (self.current_inventory or {}).get('parts', {}).values():
            if str(part.get('partId')) == str(part_id):
                return part
        return None

    def _local_path(self, part_id):
        directory = self._sync_directory()
        part = self._part_record(part_id)
        if not directory or not part:
            return None
        synced = self._synced_part_paths.get(str(part_id))
        if synced and os.path.isfile(synced) and os.path.commonpath((directory, synced)) == directory:
            return synced
        filename = self._download_filename(part)
        if not filename:
            return None
        target = os.path.realpath(os.path.join(directory, filename))
        return target if os.path.commonpath((directory, target)) == directory else None

    def open_parts(self):
        selected = self._selected_parts()
        if not selected:
            self._error('Open parts', 'Select one or more parts first.')
            return
        missing = []
        errors = []
        last = None
        for name, part_id in selected:
            path = self._local_path(part_id)
            if not path or not os.path.isfile(path):
                missing.append(name)
                continue
            try:
                doc = next((d for d in FreeCAD.listDocuments().values()
                            if getattr(d, 'FileName', '') and
                            os.path.realpath(d.FileName) == path), None)
                last = doc or FreeCAD.openDocument(path)
            except Exception as exc:
                errors.append('{}: {}'.format(name, exc))
        if last:
            FreeCAD.setActiveDocument(last.Name)
            try:
                FreeCADGui.activeDocument().activeView().fitAll()
            except Exception:
                pass
        if missing or errors:
            self._error('Open parts', 'Not downloaded (sync first): {}\n{}'.format(
                ', '.join(missing), '\n'.join(errors)))
        else:
            self.status.setText('Opened {} part(s).'.format(len(selected)))

    def checkout_parts(self):
        selected = self._selected_parts()
        if not selected:
            self._error('Check out', 'Select one or more parts first.')
            return
        if QtWidgets.QMessageBox.question(
                self, 'Check Out', 'Check out {} selected part(s)?'.format(len(selected)),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return
        from parts_manager_plm import plmupload
        uploader = plmupload.PlmUploader(connection=self.connection)
        successes, errors = 0, []
        for name, part_id in selected:
            try:
                uploader.check_out_part(part_id)
                successes += 1
            except Exception as exc:
                errors.append('{}: {}'.format(name, exc))
        self.refresh_inventory()
        self.status.setText('Checked out {} part(s).'.format(successes))
        if errors:
            self._error('Check out', '\n'.join(errors))

    def checkin_parts(self):
        selected = self._selected_parts()
        if not selected:
            self._error('Check in', 'Select one or more parts first.')
            return
        missing = [name for name, pid in selected if not self._local_path(pid)
                   or not os.path.isfile(self._local_path(pid))]
        if missing:
            self._error('Check in', 'Sync these parts to the computer first:\n' + '\n'.join(missing))
            return
        # Use the existing PLM check-in dialog, which handles linked documents,
        # lifecycle permissions, tags and upload processing.
        self.open_parts()
        from parts_manager_plm import plmcheckin
        plmcheckin.show_checkin_dialog()
        self.refresh_inventory()

    def edit_tags(self):
        selected = self._selected_parts()
        if not selected:
            self._error('Edit tags', 'Select one or more parts first.')
            return
        try:
            tags = PlmTags.get_tags(self.connection)
        except Exception as exc:
            self._error('Load PLM tags', exc)
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Edit PLM Tags')
        dialog.resize(450, 500)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel('Select tags to replace on all selected parts:'))
        tree = QtWidgets.QTreeWidget()
        tree.setHeaderLabels(['PLM Tags'])
        layout.addWidget(tree)
        nodes, by_name = {}, {}
        for tag in tags:
            if not isinstance(tag, dict) or tag.get('id') is None:
                continue
            node = QtWidgets.QTreeWidgetItem([str(tag.get('name', ''))])
            node.setFlags(node.flags() | QtCore.Qt.ItemIsUserCheckable)
            node.setCheckState(0, QtCore.Qt.Unchecked)
            nodes[str(tag['id'])] = (node, tag)
            by_name[str(tag.get('name', ''))] = node
        for node, tag in nodes.values():
            parent = by_name.get(str(tag.get('parent', '')))
            if parent and parent is not node:
                parent.addChild(node)
            else:
                tree.addTopLevelItem(node)
        tree.expandToDepth(1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        ids = [int(key) for key, (node, _) in nodes.items()
               if node.checkState(0) == QtCore.Qt.Checked]
        if QtWidgets.QMessageBox.question(
                self, 'Replace PLM Tags',
                'Replace tags for {} selected part(s) with {} selected tag(s)?'.format(
                    len(selected), len(ids)),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return
        errors = []
        for name, part_id in selected:
            try:
                PlmTags.set_part_tags(part_id=part_id, tag_ids=ids,
                                      connection=self.connection)
            except Exception as exc:
                errors.append('{}: {}'.format(name, exc))
        self.refresh_inventory()
        if errors:
            self._error('Edit tags', '\n'.join(errors))
        else:
            self.status.setText('Updated tags for {} part(s).'.format(len(selected)))

    def _apply_selected(self, action, label):
        workspace_id = self._workspace_id()
        selected = self._selected_parts()
        if workspace_id is None or not selected:
            QtWidgets.QMessageBox.information(self, 'Global Workspaces', 'Select one or more parts first.')
            return
        answer = QtWidgets.QMessageBox.question(self, label,
            '{} {} part(s)?\n\n{}'.format(label, len(selected),
            '\n'.join(name for name, _ in selected)),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        if answer != QtWidgets.QMessageBox.Yes:
            return
        failures = []
        for name, part_id in selected:
            try:
                if part_id is None:
                    raise ValueError('Missing PLM part ID')
                # Read revision from each successful mutation: prevents stale-revision conflicts.
                result = action(workspace_id, part_id, self._revision())
                if isinstance(result.get('inventory'), dict):
                    self.current_inventory = result['inventory']
                else:
                    self.current_inventory = self.api.inventory(workspace_id)['inventory']
            except Exception as exc:
                failures.append('{}: {}'.format(name, exc))
                break  # Stop on conflict; later operations must not use a stale revision.
        self.refresh_inventory()
        if failures:
            self._error(label + ' failed', '\n'.join(failures))

    def remove_parts(self):
        self._apply_selected(self.api.remove_part, 'Remove')

    def approve_versions(self):
        """Approve server revisions and immediately update their local CAD files.

        Each approval is committed on the server before its download. A failed
        download is reported explicitly; it does not undo server approval.
        """
        workspace_id = self._workspace_id()
        selected = self._selected_parts()
        if workspace_id is None or not selected:
            QtWidgets.QMessageBox.information(
                self, 'Approve Latest Version', 'Select one or more parts first.')
            return
        directory = self._sync_directory()
        if not directory:
            self._error('Approve Latest Version',
                        'Configure a local Global Workspace folder using Sync first. '
                        'No versions have been approved.')
            return
        answer = QtWidgets.QMessageBox.question(
            self, 'Approve Latest Version',
            'Approve the latest CAD version for {} selected part(s) and replace '
            'their local downloaded copies in:\n{}?\n\n'
            'Open FreeCAD documents with unsaved changes will not be overwritten.'.format(
                len(selected), directory),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if answer != QtWidgets.QMessageBox.Yes:
            return

        approved = []
        updated = []
        failures = []
        self.approve_button.setEnabled(False)
        try:
            for name, part_id in selected:
                try:
                    if part_id is None:
                        raise ValueError('Missing PLM part ID')
                    part = self._part_record(part_id)
                    if not part:
                        raise ValueError('Part is missing from workspace inventory')
                    filename = self._download_filename(part)
                    if not filename:
                        raise ValueError('No usable CAD filename')
                    target = os.path.realpath(os.path.join(directory, filename))
                    if os.path.commonpath((directory, target)) != directory:
                        raise ValueError('Unsafe CAD filename')
                    # Do not approve a version that cannot be safely downloaded.
                    # The shared downloader also checks linked archive documents.
                    if PlmDownload._has_unsaved_open_document(target):
                        raise ValueError('Local file is open in FreeCAD with unsaved changes')
                    result = self.api.approve_version(workspace_id, part_id, self._revision())
                    approved.append(name)
                    if isinstance(result.get('inventory'), dict):
                        self.current_inventory = result['inventory']
                    else:
                        self.current_inventory = self.api.inventory(workspace_id)['inventory']
                except Exception as exc:
                    failures.append('{}: approval failed: {}'.format(name, exc))
                    break  # Inventory revision might be stale; stop approving.

                # Use the exact same downloader as the working Local Workspace.
                # The returned path is recorded for Open and Local Status.
                try:
                    fresh = self._part_record(part_id) or part
                    result_path = PlmDownload.download_part(
                        connection=self.connection,
                        part_id=part_id,
                        part_data={
                            'originalName': filename,
                            'name': filename,
                            'file': filename,
                            'version': fresh.get('latestVersion'),
                        },
                        workspace=directory,
                        force=True,
                        destination_path=target,
                    )
                    if not result_path or not os.path.isfile(result_path):
                        raise RuntimeError('Download failed; server approval succeeded')
                    self._synced_part_paths[str(part_id)] = os.path.realpath(result_path)
                    updated.append(name)
                except Exception as exc:
                    failures.append('{}: approved on server, but local update failed: {}'.format(
                        name, exc))
        finally:
            self.approve_button.setEnabled(True)
            self.refresh_inventory()

        summary = 'Approved: {}. Local files updated: {}.'.format(
            len(approved), len(updated))
        if failures:
            summary += '\n\n' + '\n'.join(failures)
        self.status.setText(summary)
        if failures:
            QtWidgets.QMessageBox.warning(self, 'Approve Latest Version', summary)
        else:
            QtWidgets.QMessageBox.information(self, 'Approve Latest Version', summary)

    def manage_members(self):
        workspace_id = self._workspace_id()
        if workspace_id is None:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Global Workspace Sharing')
        dialog.resize(550, 360)
        layout = QtWidgets.QVBoxLayout(dialog)
        members_table = QtWidgets.QTableWidget()
        members_table.setColumnCount(2)
        members_table.setHorizontalHeaderLabels(['Username', 'Role'])
        members_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        members_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        members_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        members_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(members_table)
        member_records = []

        def reload_members():
            member_records[:] = self.api.members(workspace_id)
            members_table.setRowCount(len(member_records))
            for row, member in enumerate(member_records):
                members_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(member.get('username', ''))))
                members_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(member.get('role', ''))))

        buttons = QtWidgets.QHBoxLayout()

        def add_member():
            username, ok = QtWidgets.QInputDialog.getText(dialog, 'Share Workspace', 'Username:')
            if not ok or not username.strip():
                return
            role, ok = QtWidgets.QInputDialog.getItem(
                dialog, 'Share Workspace', 'Access role:', ['VIEWER', 'EDITOR'], 0, False)
            if not ok:
                return
            try:
                self.api.set_member(workspace_id, username.strip(), str(role))
                reload_members()
            except Exception as exc:
                self._error('Share workspace failed', exc)

        def remove_member():
            row = members_table.currentRow()
            if row < 0 or row >= len(member_records):
                return
            member = member_records[row]
            answer = QtWidgets.QMessageBox.question(dialog, 'Remove Member',
                'Remove {} from this workspace?'.format(member.get('username', '')),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if answer != QtWidgets.QMessageBox.Yes:
                return
            try:
                self.api.remove_member(workspace_id, member['userId'])
                reload_members()
            except Exception as exc:
                self._error('Remove member failed', exc)

        self._button('Add / Update Member', add_member, buttons)
        self._button('Remove Member', remove_member, buttons)
        buttons.addStretch()
        self._button('Close', dialog.accept, buttons)
        layout.addLayout(buttons)
        try:
            reload_members()
        except Exception as exc:
            self._error('Load members failed', exc)
            return
        dialog.exec_()

    def open_manager(self):
        base = str(getattr(self.connection, 'url', '') or '').strip()
        if not base:
            QtWidgets.QMessageBox.warning(self, 'Global Workspaces', 'No PLM server URL configured.')
            return
        workspace_id = self._workspace_id()
        endpoint = 'workspace/show/{}'.format(workspace_id) if workspace_id is not None else 'workspace/index'
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(urljoin(base.rstrip('/') + '/', endpoint)))