# -*- coding: utf-8 -*-
"""Standalone PLM Check-In dialog for FreeCAD 1.1.

Uses the existing login.py connection and plmupload.py upload protocol.
The workspace preference is read from connection.settings (key: workspace).
"""
import os
import traceback

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui

import Login as login
import plmupload


ICON_DIR = os.path.join(
    FreeCAD.getUserAppDataDir(),
    "Mod",
    "part-manager-plm_for_freecad",
    "icons"
)

def _enum(owner, old_name, new_path):
    value = getattr(owner, old_name, None)
    if value is not None:
        return value
    target = owner
    for part in new_path.split('.'):
        target = getattr(target, part)
    return target


USER_ROLE = _enum(QtCore.Qt, 'UserRole', 'ItemDataRole.UserRole')
CHECKED = _enum(QtCore.Qt, 'Checked', 'CheckState.Checked')
UNCHECKED = _enum(QtCore.Qt, 'Unchecked', 'CheckState.Unchecked')
ALIGN_RIGHT = _enum(QtCore.Qt, 'AlignRight', 'AlignmentFlag.AlignRight')


def _text(value):
    return '' if value is None else str(value)


def format_bytes(number):
    try:
        number = float(number)
    except (TypeError, ValueError):
        return 'Unknown'
    if number < 1024:
        return '{:.0f} B'.format(number)
    if number < 1024 ** 2:
        return '{:.1f} KB'.format(number / 1024)
    if number < 1024 ** 3:
        return '{:.1f} MB'.format(number / (1024 ** 2))
    return '{:.2f} GB'.format(number / (1024 ** 3))


def document_path(doc):
    path = _text(getattr(doc, 'FileName', '')).strip()
    return os.path.abspath(os.path.expanduser(path)) if path else ''


def document_size(doc):
    path = document_path(doc)
    try:
        return os.path.getsize(path) if path and os.path.isfile(path) else 0
    except OSError:
        return 0


def is_link(obj):
    type_id = _text(getattr(obj, 'TypeId', ''))
    return type_id in ('App::Link', 'Assembly::AssemblyLink') or (
        'Link' in type_id and hasattr(obj, 'LinkedObject')
    )


def linked_document(obj):
    linked = getattr(obj, 'LinkedObject', None)
    if linked is None:
        try:
            linked = obj.getLinkedObject()
        except Exception:
            linked = None
    return getattr(linked, 'Document', None) if linked is not None else None


def collect_documents(root_doc):
    """Collect the active document plus recursively referenced linked documents."""
    result, visited_docs, visited_objects = [], set(), set()

    def visit_doc(doc):
        if doc is None:
            return
        doc_key = _text(getattr(doc, 'Name', '')) or str(id(doc))
        if doc_key in visited_docs:
            return
        visited_docs.add(doc_key)
        result.append(doc)

        def visit_obj(obj):
            object_key = (doc_key, _text(getattr(obj, 'Name', '')) or str(id(obj)))
            if object_key in visited_objects:
                return
            visited_objects.add(object_key)
            if is_link(obj):
                visit_doc(linked_document(obj))
            for child in (getattr(obj, 'Group', None) or []):
                visit_obj(child)
            try:
                children = obj.claimChildren()
            except Exception:
                children = []
            for child in (children or []):
                visit_obj(child)

        for obj in (getattr(doc, 'Objects', None) or []):
            visit_obj(obj)

    visit_doc(root_doc)
    return result


class PlmCheckInDialog(QtGui.QDialog):
    COL_INCLUDE, COL_PART, COL_FILE, COL_STATUS, COL_VERSION, COL_MODIFIED, COL_SIZE = range(7)
    def __init__(self, parent=None):
        super(PlmCheckInDialog, self).__init__(parent)
        self.setWindowTitle('PLM Check-In')
        self.resize(1080, 620)
        self.setMinimumSize(820, 440)
        self.connection = login.get_connection()
        self.documents = []
        self.document_by_name = {}
        self.server_parts = {}
        self.server_info = {}
        self._loading_table = False
        self._build_ui()
        self.refresh()

    def _document_modified(self, doc):
        """Compare the local file modification time with its upload baseline."""

        path = document_path(doc)

        # Unsaved or missing files cannot be compared reliably.
        if not path or not os.path.isfile(path):
            return True

        baseline = plmupload.PlmUploader._get_modified_baseline()

        active_doc = FreeCAD.ActiveDocument

        if active_doc is None:
            return True

        assembly_path = document_path(active_doc)

        if not assembly_path:
            return True

        assembly_baseline = baseline.get(
            os.path.abspath(assembly_path),
            {}
        )

        absolute_path = os.path.abspath(path)

        previous_mtime = assembly_baseline.get(absolute_path)

        current_mtime = plmupload.PlmUploader._get_file_mtime_ns(
            absolute_path
        )

        if current_mtime is None:
            return True

        # No baseline means that we cannot confirm the file is unchanged.
        if previous_mtime is None:
            return True

        return current_mtime > int(previous_mtime)
    def _build_ui(self):
        layout = QtGui.QVBoxLayout(self)
        info = QtGui.QGridLayout()
        self.connection_label = QtGui.QLabel('Connection: unknown')
        self.version_label = QtGui.QLabel('Server version: unknown')
        self.workspace_label = QtGui.QLabel('Workspace: unknown')
        self.size_label = QtGui.QLabel('Estimated upload: 0 B')
        info.addWidget(self.connection_label, 0, 0)
        info.addWidget(self.version_label, 0, 1)
        info.addWidget(self.workspace_label, 1, 0, 1, 2)
        info.addWidget(self.size_label, 1, 2)
        layout.addLayout(info)

        self.table = QtGui.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            'Include',
            'Part / Document',
            'File',
            'PLM Status',
            'Version',
            'Modified',
            'File Size'
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        hv = self.table.horizontalHeader()
        try:
            mode = QtGui.QHeaderView.ResizeMode

            hv.setSectionResizeMode(self.COL_INCLUDE, mode.ResizeToContents)
            hv.setSectionResizeMode(self.COL_PART, mode.ResizeToContents)
            hv.setSectionResizeMode(self.COL_FILE, mode.Stretch)
            hv.setSectionResizeMode(self.COL_STATUS, mode.ResizeToContents)
            hv.setSectionResizeMode(self.COL_VERSION, mode.ResizeToContents)
            hv.setSectionResizeMode(self.COL_MODIFIED, mode.ResizeToContents)
            hv.setSectionResizeMode(self.COL_SIZE, mode.ResizeToContents)

        except AttributeError:
            hv.setResizeMode(self.COL_INCLUDE, QtGui.QHeaderView.ResizeToContents)
            hv.setResizeMode(self.COL_PART, QtGui.QHeaderView.ResizeToContents)
            hv.setResizeMode(self.COL_FILE, QtGui.QHeaderView.Stretch)
            hv.setResizeMode(self.COL_STATUS, QtGui.QHeaderView.ResizeToContents)
            hv.setResizeMode(self.COL_VERSION, QtGui.QHeaderView.ResizeToContents)
            hv.setResizeMode(self.COL_MODIFIED, QtGui.QHeaderView.ResizeToContents)
            hv.setResizeMode(self.COL_SIZE, QtGui.QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.status_label = QtGui.QLabel('Ready.')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QtGui.QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        buttons = QtGui.QHBoxLayout()
        self.refresh_button = QtGui.QPushButton('Refresh')
        self.remove_button = QtGui.QPushButton('Remove Selected')
        self.include_button = QtGui.QPushButton('Include All')
        self.exclude_button = QtGui.QPushButton('Exclude All')
        self.checkin_button = QtGui.QPushButton('Check-In')
        self.checkin_button.setDefault(True)
        for button in (self.refresh_button, self.remove_button,
                       self.include_button, self.exclude_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.checkin_button)
        layout.addLayout(buttons)

        self.refresh_button.clicked.connect(self.refresh)
        self.remove_button.clicked.connect(self.remove_selected)
        self.include_button.clicked.connect(lambda: self.set_all_included(True))
        self.exclude_button.clicked.connect(lambda: self.set_all_included(False))
        self.checkin_button.clicked.connect(self.check_in)
        self.table.itemChanged.connect(self._item_changed)

    def _connection(self):
        conn = self.connection

        connected = bool(getattr(conn, 'connected', False))
        url = _text(getattr(conn, 'url', '')).strip().rstrip('/')
        session = getattr(conn, 'session', None)

        # Use the same settings store as Workspace.py.
        settings = QtCore.QSettings(
            QtCore.QSettings.IniFormat,
            QtCore.QSettings.UserScope,
            "PMPLM",
            "PartsManager"
        )

        workspace = _text(
            settings.value('workspace', '')
        ).strip()

        # Log the state so we can see why the request may be skipped.
        FreeCAD.Console.PrintMessage(
            "\n[PLM Check-In] Connection diagnostics:\n"
            "  Connected: {}\n"
            "  URL configured: {}\n"
            "  Session available: {}\n"
            "  Workspace: {}\n".format(
                connected,
                bool(url),
                session is not None,
                workspace or '(empty)'
            )
        )

        return connected, url, session, workspace

    def _server_info(self, url, session):
        response = session.get(url + '/plmJson/serverInfo', timeout=15)
        response.raise_for_status()
        value = response.json()
        return value if isinstance(value, dict) else {}

    def _workspace_status(self, url, session, workspace, documents):
        """
        Retrieve PLM status using the same API contract as Workspace.py.

        POST /plmJson/workspaceParts

        Request:
            {
                "parts": [
                    {
                        "name": "part.FCStd",
                        "relativePath": "subfolder/part.FCStd"
                    }
                ]
            }
        """
        if not workspace:
            return {}

        workspace_abs = os.path.abspath(
            os.path.expanduser(workspace)
        )

        parts = []

        for doc in documents:
            path = document_path(doc)

            if not path:
                continue

            filename = os.path.basename(path)

            try:
                relative_path = os.path.relpath(
                    path,
                    workspace_abs
                )
            except (ValueError, OSError):
                relative_path = filename

            # Don't send paths outside the workspace as ../something.FCStd.
            if relative_path == os.pardir or relative_path.startswith(
                    os.pardir + os.sep
            ):
                relative_path = filename

            relative_path = relative_path.replace("\\", "/")

            parts.append({
                "name": filename,
                "relativePath": relative_path,
            })

        if not parts:
            return {}

        # Match the working Workspace.py request format exactly.
        payload = {
            "parts": parts,
        }

        response = session.post(
            url.rstrip("/") + "/plmJson/workspaceParts",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        #-------debug-----------------------
        FreeCAD.Console.PrintMessage(
            "\n===== CHECK-IN WORKSPACE STATUS DEBUG =====\n"
        )
        FreeCAD.Console.PrintMessage(
            "Request URL: {}\n".format(
                url.rstrip("/") + "/plmJson/workspaceParts"
            )
        )
        FreeCAD.Console.PrintMessage(
            "Request payload:\n{}\n".format(
                __import__("json").dumps(payload, indent=2)
            )
        )
        FreeCAD.Console.PrintMessage(
            "Server response:\n{}\n".format(
                __import__("json").dumps(data, indent=2)
            )
        )
        FreeCAD.Console.PrintMessage(
            "===========================================\n"
        )

        #----end debug------------------------



        if not isinstance(data, dict):
            raise RuntimeError(
                "Unexpected workspaceParts response: expected a JSON object."
            )

        returned_parts = data.get("parts", [])

        inventory = {}

        for part in returned_parts:
            if not isinstance(part, dict):
                continue

            name = str(part.get("name") or "")
            relative_path = str(part.get("relativePath") or "")

            # Use the same normalized path key as Workspace.py.
            normalized_path = relative_path.replace("\\", "/").lower()

            if not normalized_path and name:
                normalized_path = name.replace("\\", "/").lower()

            latest_version = part.get("latestVersion")
            if latest_version is None:
                latest_version = "—"

            entry = {
                "version": str(latest_version),
                "exists": part.get("existsInPlm", False),
                "status": part.get("plmStatus", ""),
                "plmPartId": part.get("plmPartId"),
                "part": part,
            }

            if normalized_path:
                inventory[normalized_path] = entry

            if name:
                filename_key = os.path.basename(
                    name.replace("\\", "/")
                ).lower()

                inventory.setdefault(filename_key, entry)

        return inventory

    def refresh(self):
        FreeCAD.Console.PrintMessage(
            "\n[PLM Check-In] refresh() called\n"
        )

        self.progress.setValue(0)
        self.table.setRowCount(0)
        self.documents = []
        self.document_by_name = {}
        self.server_parts = {}
        self.server_info = {}

        active = FreeCAD.ActiveDocument

        if active is None:
            self.connection_label.setText(
                'Connection: no active document'
            )
            self.version_label.setText(
                'Server version: unavailable'
            )
            self.workspace_label.setText(
                'Workspace: unknown'
            )
            self.status_label.setText(
                'Open a FreeCAD document before checking in.'
            )
            self._update_size()
            return

        self.documents = collect_documents(active)

        connected, url, session, workspace = self._connection()

        self.connection_label.setText(
            'Connection: ' + (
                'Connected' if connected else 'Not connected'
            )
        )
        self.workspace_label.setText(
            'Workspace: ' + (workspace or 'not configured')
        )

        if connected and url and session:
            # Fetch server information.
            try:
                self.server_info = self._server_info(
                    url, session
                )

                version = (
                        self.server_info.get('serverBuild')
                        or self.server_info.get('serverVersion')
                        or self.server_info.get('buildDate')
                        or 'unknown'
                )

                self.version_label.setText(
                    'Server version: ' + _text(version)
                )

            except Exception as exc:
                self.version_label.setText(
                    'Server version: unavailable'
                )
                FreeCAD.Console.PrintError(
                    '[PLM Check-In] serverInfo failed: {}\n'
                    .format(exc)
                )

            # Fetch workspace status.
            if workspace:
                FreeCAD.Console.PrintMessage(
                    '[PLM Check-In] Requesting workspace status...\n'
                )

                try:
                    self.server_parts = self._workspace_status(
                        url,
                        session,
                        workspace,
                        self.documents
                    )

                    FreeCAD.Console.PrintMessage(
                        '[PLM Check-In] Inventory entries received: {}\n'
                        .format(len(self.server_parts))
                    )

                except Exception as exc:
                    self.status_label.setText(
                        'Could not retrieve PLM status: {}'.format(
                            exc
                        )
                    )

                    FreeCAD.Console.PrintError(
                        '[PLM Check-In] workspaceParts failed: {}\n'
                        .format(exc)
                    )
                    FreeCAD.Console.PrintError(
                        traceback.format_exc() + '\n'
                    )

            else:
                FreeCAD.Console.PrintWarning(
                    '[PLM Check-In] Workspace is empty; '
                    'status request skipped.\n'
                )

        else:
            self.version_label.setText(
                'Server version: unavailable (not connected)'
            )

            FreeCAD.Console.PrintWarning(
                '[PLM Check-In] Status request skipped: '
                'connection, URL, or session is missing.\n'
            )

        self._populate_table()
        self._update_size()

        if not self.status_label.text().startswith(
                'Could not retrieve'
        ):
            self.status_label.setText(
                'Found {} document(s) including linked parts.'
                .format(len(self.documents))
            )

    def _server_entry(self, doc):
        """Find the server inventory record for a FreeCAD document."""

        path = document_path(doc)

        if not path:
            return {}

        candidates = [
            os.path.basename(path).lower()
        ]

        workspace = self._connection()[3]

        if workspace:
            workspace_abs = os.path.abspath(
                os.path.expanduser(workspace)
            )

            try:
                relative_path = os.path.relpath(
                    path,
                    workspace_abs
                )
            except (ValueError, OSError):
                relative_path = os.path.basename(path)

            relative_path = relative_path.replace("\\", "/").lower()

            if (
                    relative_path != ".."
                    and not relative_path.startswith("../")
            ):
                candidates.insert(0, relative_path)

        for candidate in candidates:
            entry = self.server_parts.get(candidate)

            if entry:
                return entry

        return {}

    def _plm_status(self, doc):
        entry = self._server_entry(doc)

        if not entry:
            return "Not found" if self.server_parts else "Unavailable"

        part = entry.get("part", {})

        status = (
                entry.get("status")
                or part.get("plmStatus")
                or part.get("status")
        )

        if status:
            return _text(status)

        if entry.get("exists", part.get("existsInPlm", False)):
            return "In PLM"

        return "Not in PLM"

    def _populate_table(self):
        self._loading_table = True
        self.table.setRowCount(0)
        active_name = _text(getattr(FreeCAD.ActiveDocument, 'Name', ''))
        for doc in self.documents:
            row = self.table.rowCount()
            self.table.insertRow(row)

            name = _text(getattr(doc, 'Name', ''))
            label = _text(getattr(doc, 'Label', name))
            path = document_path(doc)
            size = document_size(doc)

            # Determine modification state.
            modified = self._document_modified(doc)

            # Retrieve the server inventory record.
            entry = self._server_entry(doc)

            server_version = (
                entry.get('version', '—')
                if entry
                else '—'
            )

            # Include column.
            include = QtGui.QTableWidgetItem()
            include.setFlags(
                include.flags() | QtCore.Qt.ItemIsUserCheckable
            )

            include.setCheckState(
                CHECKED if modified else UNCHECKED
            )

            include.setData(USER_ROLE, name)

            self.table.setItem(
                row,
                self.COL_INCLUDE,
                include
            )

            # Part / Document column.
            part_item = QtGui.QTableWidgetItem(
                label + (' (active)' if name == active_name else '')
            )

            part_item.setData(USER_ROLE, name)

            if name == active_name:
                font = part_item.font()
                font.setBold(True)
                part_item.setFont(font)

            self.table.setItem(
                row,
                self.COL_PART,
                part_item
            )

            # File column.
            file_item = QtGui.QTableWidgetItem(
                os.path.basename(path)
                if path
                else '(unsaved document)'
            )

            file_item.setToolTip(
                path or 'Save this document before check-in.'
            )

            self.table.setItem(
                row,
                self.COL_FILE,
                file_item
            )

            # PLM Status column.
            status = self._plm_status(doc)

            status_item = QtGui.QTableWidgetItem(status)

            if status.upper() == 'LOCKED':
                status_item.setForeground(
                    QtGui.QBrush(QtGui.QColor(200, 0, 0))
                )

            self.table.setItem(
                row,
                self.COL_STATUS,
                status_item
            )

            # Version column.
            version_item = QtGui.QTableWidgetItem(
                _text(server_version)
            )

            version_item.setTextAlignment(ALIGN_RIGHT)

            self.table.setItem(
                row,
                self.COL_VERSION,
                version_item
            )

            # Modified column.
            modified_item = QtGui.QTableWidgetItem(
                'Yes' if modified else 'No'
            )

            modified_item.setData(
                USER_ROLE,
                modified
            )

            self.table.setItem(
                row,
                self.COL_MODIFIED,
                modified_item
            )

            # File Size column.
            size_item = QtGui.QTableWidgetItem(
                format_bytes(size)
            )

            size_item.setTextAlignment(ALIGN_RIGHT)
            size_item.setData(USER_ROLE, size)

            self.table.setItem(
                row,
                self.COL_SIZE,
                size_item
            )

            self.document_by_name[name] = doc

        self._loading_table = False

    def _item_changed(self, item):
        if not self._loading_table and item.column() == self.COL_INCLUDE:
            self._update_size()

    def included_documents(self):
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_INCLUDE)
            if item and item.checkState() == CHECKED:
                doc = self.document_by_name.get(_text(item.data(USER_ROLE)))
                if doc is not None:
                    result.append(doc)
        return result

    def _update_size(self):
        docs = self.included_documents()
        total = sum(document_size(doc) for doc in docs)
        existing_count = sum(1 for doc in docs if document_path(doc) and os.path.isfile(document_path(doc)))
        self.size_label.setText('Estimated upload: {} ({} file(s))'.format(format_bytes(total), existing_count))

    def set_all_included(self, include):
        self._loading_table = True
        state = CHECKED if include else UNCHECKED
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_INCLUDE)
            if item:
                item.setCheckState(state)
        self._loading_table = False
        self._update_size()

    def remove_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            QtGui.QMessageBox.information(self, 'Remove files', 'Select one or more rows first.')
            return
        # Removing a row excludes that document from the upload list for this dialog.
        for row in rows:
            self.table.removeRow(row)
        self._update_size()

    def _progress(self, value, message=None):
        try:
            if isinstance(value, (tuple, list)):
                value, message = value[0], (value[1] if len(value) > 1 else message)
            self.progress.setValue(int(value))
            if message:
                self.status_label.setText(str(message))
            QtGui.QApplication.processEvents()
        except Exception:
            pass

    def check_in(self):
        connected, url, session, workspace = self._connection()
        if not connected:
            QtGui.QMessageBox.warning(self, 'PLM Check-In', 'Connect to the PLM server first.')
            return
        docs = self.included_documents()
        if not docs:
            QtGui.QMessageBox.warning(self, 'PLM Check-In', 'No files are included for upload.')
            return
        unsaved = [
            _text(getattr(doc, 'Label', getattr(doc, 'Name', 'document')))
            for doc in docs if not document_path(doc) or not os.path.isfile(document_path(doc))
        ]
        if unsaved:
            QtGui.QMessageBox.warning(
                self, 'Save documents first',
                'Save these documents in FreeCAD before check-in:\n\n' + '\n'.join(unsaved)
            )
            return

        total = sum(document_size(doc) for doc in docs)
        maximum = self.server_info.get('maximumFileUploadSize')
        try:
            maximum = int(maximum) if maximum is not None else None
        except (TypeError, ValueError):
            maximum = None
        if maximum and total > maximum:
            QtGui.QMessageBox.warning(
                self, 'Upload size limit',
                'Selected files total {}. Server maximum is {}.'.format(format_bytes(total), format_bytes(maximum))
            )
            return
        if total > 500 * 1024 * 1024:
            answer = QtGui.QMessageBox.question(
                self, 'Large upload',
                'Selected files total {}. Continue?'.format(format_bytes(total)),
                QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
                QtGui.QMessageBox.No
            )
            if answer != QtGui.QMessageBox.Yes:
                return

        self.checkin_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.status_label.setText('Starting check-in...')
        self.progress.setValue(0)
        try:
            uploader = plmupload.PlmUploader(connection=self.connection, documents=docs)
            try:
                uploader.upload_documents(documents=docs, progress_callback=self._progress)
            except TypeError as exc:
                if 'unexpected keyword' not in str(exc) and 'positional' not in str(exc):
                    raise
                uploader.upload_documents(docs, progress_callback=self._progress)
            self.progress.setValue(100)
            self.status_label.setText('Check-in completed successfully.')
            QtGui.QMessageBox.information(self, 'PLM Check-In', 'Selected files were checked in successfully.')
            self.refresh()
        except Exception as exc:
            message = 'Check-in failed: {}'.format(exc)
            self.status_label.setText(message)
            FreeCAD.Console.PrintError(message + '\n' + traceback.format_exc() + '\n')
            QtGui.QMessageBox.critical(self, 'PLM Check-In', message)
        finally:
            self.checkin_button.setEnabled(True)
            self.refresh_button.setEnabled(True)


_dialog = None


def show_checkin_dialog():
    """Open the check-in window as a normal Qt dialog, not a FreeCAD task panel."""
    global _dialog

    try:
        if _dialog is not None:
            _dialog.close()
    except Exception:
        pass

    parent = FreeCADGui.getMainWindow()

    _dialog = PlmCheckInDialog(parent)

    # Open as a normal, non-modal window.
    # Do not use FreeCADGui.Control.showDialog().
    _dialog.setModal(False)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()

    return _dialog


class PMPLM_CheckIn:
    """Open the PLM Check-In dialog."""


    def GetResources(self):
        return {
            "Pixmap": os.path.join(
                ICON_DIR,
                "upload.svg"
            ),
            "MenuText": "Check In Parts",
            "ToolTip": "Check in parts to the PLM server"
        }

    def Activated(self):
        show_checkin_dialog()

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


def register_command():
    FreeCADGui.addCommand(
        "PMPLM_CheckIn",
        PMPLM_CheckIn()
    )