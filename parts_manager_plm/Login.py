# -*- coding: utf-8 -*-
"""Parts Manager PLM login and server capability display for FreeCAD 1.1."""

import os
import requests

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

ICON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons"
)

KNOWN_SERVER_FEATURES = {
    "tags": "Browse Tags",
    "partsByTag": "Parts by Tag",
    "workspaceParts": "Workspace Parts",
    "setPartTags": "Edit Part Tags",
    "searchParts": "Search Parts",
    "checkOutPart": "Check Out Part",
    "cancelCheckOut": "Cancel Check Out",
    "releasePart": "Release Part",
    "createRevision": "Create Revision",
    "partHistory": "Part History",
}



class PlmConnection:
    """Shared PLM connection state and authenticated HTTP session."""

    def __init__(self):
        self.settings = QtCore.QSettings("PMPLM", "PartsManager")
        self.session = requests.Session()
        self.connected = False
        self.user = self.settings.value("username", "Login")
        self.url = self.settings.value("url", "")
        self.passwd = ""
        self.server_info = None
        

    def save_preferences(self):
        self.user = str(self.user).strip()
        self.url = str(self.url).strip()
        if self.url and not self.url.endswith("/"):
            self.url += "/"
        self.settings.setValue("username", self.user)
        self.settings.setValue("url", self.url)

    def login(self, username, password, server_url):
        """Authenticate and verify access to a protected PLM endpoint."""
        self.user = str(username).strip()
        self.url = str(server_url).strip()
        self.passwd = ""
        self.connected = False
        self.server_info = None
        if self.url and not self.url.endswith("/"):
            self.url += "/"
        if not self.url or not self.user or not password:
            return False, "Enter the server URL, username and password."

        self.session.cookies.clear()
        try:
            response = self.session.post(
                self.url + "login/authenticate",
                data={"username": self.user, "password": password, "ajax": "true"},
                timeout=15,
                allow_redirects=True,
            )
            if response.status_code != 200:
                self.session.cookies.clear()
                return False, "Login failed: HTTP {}".format(response.status_code)

            # HTTP 200 may be an HTML login page. Verify the protected API
            # returns the expected JSON object before reporting success.
            verify = self.session.get(
                self.url + "plmJson/serverInfo", timeout=10,
                allow_redirects=True,
            )
            verify.raise_for_status()
            content_type = verify.headers.get("Content-Type", "").lower()
            if "json" not in content_type:
                raise ValueError("Server returned a non-JSON response (possibly a login page).")
            info = verify.json()
            if not isinstance(info, dict) or not any(
                key in info for key in
                ("features", "maximumFileUploadSize", "serverVersion", "messagingProtocolVersion")
            ):
                raise ValueError("Server did not return valid PLM server information.")

            self.server_info = info
            self.connected = True
            self.passwd = password
            self.save_preferences()
            return True, "Connected successfully."

        except (requests.RequestException, ValueError) as exc:
            self.session.cookies.clear()
            self.connected = False
            self.server_info = None
            return False, "Connection error: {}".format(exc)

    def logout(self):
        try:
            if self.connected and self.url:
                self.session.get(self.url + "logout", timeout=10)
        except requests.RequestException:
            pass
        self.session.cookies.clear()
        self.connected = False
        self.passwd = ""
        self.server_info = None

    def get_server_info(self):
        if not self.connected:
            return None
        try:
            response = self.session.get(self.url + "plmJson/serverInfo", timeout=10)
            response.raise_for_status()
            info = response.json()
            if not isinstance(info, dict):
                raise ValueError("Expected a JSON object")
            self.server_info = info
            return info
        except (requests.RequestException, ValueError) as exc:
            FreeCAD.Console.PrintWarning(
                "Could not retrieve PLM server information: {}\n".format(exc)
            )
            return None


connection = PlmConnection()


def get_connection():
    return connection


def is_connected():
    return connection.connected


class LoginPanel:
    def __init__(self, plm_connection):
        self.connection = plm_connection
        self._login_pending = False
        self._login_failed = False
        ui_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Login.ui")
        self.form = FreeCADGui.PySideUic.loadUi(ui_path)
        self.form.userEdit.setText(self.connection.user or "")
        self.form.urlEdit.setText(self.connection.url or "")
        self.form.passEdit.clear()

        self._setup_server_information()
        self.form.connectButton.clicked.connect(self.login)
        self.form.disconnectButton.clicked.connect(self.logout)
        self.form.passEdit.returnPressed.connect(self.login)
        self.update_connection_status()
        if self.connection.connected:
            self.display_server_info(self.connection.server_info)
        else:
            self.clear_server_info()
        QtCore.QTimer.singleShot(0, self.form.passEdit.setFocus)

    def _setup_server_information(self):
        """Replace legacy labels with a read-only feature list at runtime."""
        for name in ("serverVersionValue", "messagingProtocolVersionValue"):
            widget = getattr(self.form, name, None)
            if widget is None:
                continue
            parent = widget.parentWidget()
            layout = parent.layout() if parent is not None else None
            if layout is not None and isinstance(layout, QtWidgets.QFormLayout):
                row, role = layout.getWidgetPosition(widget)
                if row >= 0:
                    layout.removeRow(row)
                    continue
            if layout is not None and isinstance(layout, QtWidgets.QGridLayout):
                index = layout.indexOf(widget)
                if index >= 0:
                    row, col, rowspan, colspan = layout.getItemPosition(index)
                    # Remove matching label immediately to the left.
                    if col > 0:
                        label_item = layout.itemAtPosition(row, col - 1)
                        if label_item and label_item.widget():
                            label_widget = label_item.widget()
                            layout.removeWidget(label_widget)
                            label_widget.hide()
                    layout.removeWidget(widget)
            widget.hide()

        # Locate the server-information group via the existing upload-size label.
        upload_value = self.form.maximumFileUploadSizeValue
        parent = upload_value.parentWidget()
        while parent is not None and not isinstance(parent, QtWidgets.QGroupBox):
            parent = parent.parentWidget()
        if parent is None:
            parent = upload_value.parentWidget()
        layout = parent.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(parent)

        self.features_label = QtWidgets.QLabel("Server Features", parent)
        self.features_tree = QtWidgets.QTreeWidget(parent)
        self.features_tree.setColumnCount(2)
        self.features_tree.setHeaderHidden(True)
        self.features_tree.setIndentation(0)
        self.features_tree.header().setStretchLastSection(True)
        self.features_tree.setRootIsDecorated(False)
        self.features_tree.setUniformRowHeights(True)
        self.features_tree.setMinimumHeight(135)
        self.features_tree.setMaximumHeight(200)
        self.features_tree.setToolTip(
            "Checked features are advertised by the server. "
            "Unknown features are shown in red."
        )
        if isinstance(layout, QtWidgets.QGridLayout):
            row = layout.rowCount()
            layout.addWidget(self.features_label, row, 0, 1, max(2, layout.columnCount()))
            layout.addWidget(self.features_tree, row + 1, 0, 1, max(2, layout.columnCount()))
        elif isinstance(layout, QtWidgets.QFormLayout):
            layout.addRow(self.features_label)
            layout.addRow(self.features_tree)
        else:
            layout.addWidget(self.features_label)
            layout.addWidget(self.features_tree)

    def login(self):
        if self._login_pending or self.connection.connected:
            return
        self._login_pending = True
        self._login_failed = False
        self.update_connection_status()
        QtWidgets.QApplication.processEvents()
        try:
            success, message = self.connection.login(
                self.form.userEdit.text(),
                self.form.passEdit.text(),
                self.form.urlEdit.text(),
            )
        finally:
            self._login_pending = False
        self._login_failed = not success
        self.form.loginMessageLabel.setText(message)
        self.update_connection_status()
        if success:
            self.display_server_info(self.connection.server_info)
            QtCore.QTimer.singleShot(2000, self.close_after_login)
        else:
            self.clear_server_info()
            self.form.passEdit.clear()
            self.form.passEdit.setFocus()

    def logout(self):
        self.connection.logout()
        self._login_failed = False
        self.form.passEdit.clear()
        self.form.loginMessageLabel.setText("Disconnected.")
        self.update_connection_status()
        self.clear_server_info()

    def update_connection_status(self):
        """Synchronize all login indicators with connection state."""

        connected = bool(self.connection.connected)

        self.form.connectButton.setEnabled(not connected)
        self.form.disconnectButton.setEnabled(connected)

        if connected:
            self.form.connectButton.setText("Connected")
            self.form.connectButton.setStyleSheet(
                "QPushButton {"
                "background-color: #70c878;"
                "color: white;"
                "}"
            )

            self.form.loginMessageLabel.setText("Connected")

        else:
            self.form.connectButton.setText("Connect")
            self.form.connectButton.setStyleSheet(
                "QPushButton {"
                "background-color: #555555;"
                "color: white;"
                "}"
            )

            self.form.loginMessageLabel.setText("Not connected")

    def close_after_login(self):
        global _dialog
        if self.connection.connected and _dialog is not None:
            _dialog.accept()

    def display_server_info(self, info):
        if not isinstance(info, dict):
            self.clear_server_info()
            return
        max_size = info.get("maximumFileUploadSize")
        try:
            size_mb = int(max_size) / (1024.0 * 1024.0)
            size_text = "{:.1f} GB".format(size_mb / 1024) if size_mb >= 1024 else "{:.0f} MB".format(size_mb)
        except (TypeError, ValueError, OverflowError):
            size_text = "Unknown"
        self.form.maximumFileUploadSizeValue.setText(size_text)
        features = info.get("features", [])
        if not isinstance(features, list):
            features = []
        enabled = {name for name in features if isinstance(name, str)}
        entries = [
            (label, key in enabled, False)
            for key, label in KNOWN_SERVER_FEATURES.items()
        ]
        entries.extend(
            (key, True, True)
            for key in sorted(enabled.difference(KNOWN_SERVER_FEATURES))
        )
        self._populate_features(entries)

    def _populate_features(self, entries):
        """Display feature indicators in two side-by-side columns."""
        self.features_tree.clear()
        rows = (len(entries) + 1) // 2
        for row in range(rows):
            item = QtWidgets.QTreeWidgetItem(self.features_tree)
            for column, index in enumerate((row, row + rows)):
                if index >= len(entries):
                    continue
                label, enabled, unknown = entries[index]
                item.setText(column, label)
                item.setCheckState(
                    column,
                    QtCore.Qt.Checked if enabled else QtCore.Qt.Unchecked
                )
                if unknown:
                    item.setForeground(
                        column, QtGui.QBrush(QtGui.QColor("#ff5555"))
                    )
                    item.setToolTip(
                        column, "Unknown feature advertised by the server"
                    )
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsUserCheckable)
        self.features_tree.resizeColumnToContents(0)

    def clear_server_info(self):
        self.form.maximumFileUploadSizeValue.setText("—")
        self._populate_features([
            (label, False, False) for label in KNOWN_SERVER_FEATURES.values()
        ])

    def refresh_server_info(self):
        self.display_server_info(self.connection.get_server_info())


_dialog = None
_login_panel = None


def show_login_dialog():
    global _dialog, _login_panel
    if _dialog is not None:
        _dialog.show()
        _dialog.raise_()
        _dialog.activateWindow()
        if _login_panel is not None:
            QtCore.QTimer.singleShot(0, _login_panel.form.passEdit.setFocus)
        return
    _dialog = QtWidgets.QDialog()
    _dialog.setWindowTitle("Parts Manager PLM Login")
    _login_panel = LoginPanel(connection)
    layout = QtWidgets.QVBoxLayout(_dialog)
    layout.addWidget(_login_panel.form)
    _dialog.resize(450, 520)
    _dialog.finished.connect(_on_dialog_finished)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    QtCore.QTimer.singleShot(0, _login_panel.form.passEdit.setFocus)


def _on_dialog_finished(result):
    global _dialog, _login_panel
    _dialog = None
    _login_panel = None


class CommandPMPLMLogin:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(ICON_DIR, "login.svg"),
            "MenuText": "Login",
            "ToolTip": "Connect to the Parts Manager PLM server",
        }

    def IsActive(self):
        return True

    def Activated(self):
        show_login_dialog()


FreeCADGui.addCommand("PMPLM_Login", CommandPMPLMLogin())