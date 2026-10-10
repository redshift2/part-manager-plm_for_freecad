import os
import requests

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets

ICON_DIR = os.path.join(
    FreeCAD.getUserAppDataDir(),
    "Mod",
    "part-manager-plm_for_freecad",
    "icons"
)
# ------------------------------------------------------------
# Shared PLM connection
# ------------------------------------------------------------

class PlmConnection:
    """Shared PLM connection state and HTTP session."""

    def __init__(self):
        self.settings = QtCore.QSettings(
            "PMPLM",
            "PartsManager"
        )

        self.session = requests.Session()
        self.connected = False
        self.user = self.settings.value("username", "Login")
        self.url = self.settings.value("url", "")
        self.passwd = ""

    def save_preferences(self):
        self.user = self.user.strip()
        self.url = self.url.strip()

        if self.url and not self.url.endswith("/"):
            self.url += "/"

        self.settings.setValue("username", self.user)
        self.settings.setValue("url", self.url)

    def login(self, username, password, server_url):
        """Authenticate using the shared HTTP session."""

        self.user = username.strip()
        self.url = server_url.strip()
        self.passwd = ""
        self.connected = False

        if self.url and not self.url.endswith("/"):
            self.url += "/"

        if not self.url or not self.user or not password:
            return False, "Enter the server URL, username and password."

        # Start with a clean session to avoid reusing stale cookies.
        self.session.cookies.clear()

        try:
            response = self.session.post(
                self.url + "login/authenticate",
                data={
                    "username": self.user,
                    "password": password,
                    "ajax": "true",
                },
                timeout=15,
                allow_redirects=True,
            )

            if response.status_code != 200:
                self.session.cookies.clear()
                return False, "Login failed: HTTP {}".format(
                    response.status_code
                )

            # IMPORTANT:
            # Insert the authentication-success validation from your
            # existing working login implementation here, if required.
            #
            # HTTP 200 alone does not guarantee successful authentication.

            self.connected = True
            self.passwd = password
            self.save_preferences()

            return True, "Connected successfully."

        except requests.RequestException as exc:
            self.session.cookies.clear()
            self.connected = False
            return False, "Connection error: {}".format(exc)

    def logout(self):
        """Log out and clear the shared session."""

        try:
            if self.connected and self.url:
                self.session.get(
                    self.url + "logout",
                    timeout=10,
                )
        except requests.RequestException:
            pass

        self.session.cookies.clear()
        self.connected = False
        self.passwd = ""

    def get_server_info(self):
        """Return server information, or None on failure."""

        if not self.connected:
            return None

        try:
            response = self.session.get(
                self.url + "plmJson/serverInfo",
                timeout=10,
            )
            response.raise_for_status()
            return response.json()

        except (requests.RequestException, ValueError) as exc:
            FreeCAD.Console.PrintWarning(
                "Could not retrieve PLM server information: {}\n".format(
                    exc
                )
            )
            return None


# One instance shared by every module importing Login.
connection = PlmConnection()


def get_connection():
    """Return the shared connection manager."""
    return connection


def is_connected():
    """Check the shared connection status."""
    return connection.connected


# ------------------------------------------------------------
# Login user interface
# ------------------------------------------------------------

class LoginPanel:

    def __init__(self, plm_connection):
        self.connection = plm_connection

        ui_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "Login.ui"
        )

        self.form = FreeCADGui.PySideUic.loadUi(ui_path)

        self.form.userEdit.setText(
            self.connection.user or ""
        )

        self.form.urlEdit.setText(
            self.connection.url or ""
        )

        self.form.passEdit.clear()

        self.form.connectButton.clicked.connect(self.login)
        self.form.disconnectButton.clicked.connect(self.logout)

        self.update_connection_status()

    def login(self):
        username = self.form.userEdit.text().strip()
        password = self.form.passEdit.text()
        server_url = self.form.urlEdit.text().strip()

        success, message = self.connection.login(
            username,
            password,
            server_url,
        )

        self.form.loginMessageLabel.setText(message)

        self.update_connection_status()

        if success:
            self.refresh_server_info()

    def logout(self):
        self.connection.logout()

        self.form.passEdit.clear()
        self.form.loginMessageLabel.setText("Disconnected.")

        self.update_connection_status()
        self.clear_server_info()

    def update_connection_status(self):
        connected = self.connection.connected

        self.form.connectButton.setEnabled(not connected)
        self.form.disconnectButton.setEnabled(connected)

        if connected:
            self.form.connectButton.setText("Connected")
            self.form.connectButton.setStyleSheet(
                "background-color: #70c878;"
            )
        else:
            self.form.connectButton.setText("Connect")
            self.form.connectButton.setStyleSheet("")

    def refresh_server_info(self):
        info = self.connection.get_server_info()

        if not info:
            return

        self.form.serverVersionValue.setText(
            str(info.get("serverVersion", "Unknown"))
        )

        self.form.messagingProtocolVersionValue.setText(
            str(info.get("messagingProtocolVersion", "Unknown"))
        )

        max_size = info.get("maximumFileUploadSize")

        if max_size is not None:
            size_mb = int(max_size) / (1024 * 1024)

            if size_mb >= 1024:
                size_text = "{:.1f} GB".format(size_mb / 1024)
            else:
                size_text = "{:.0f} MB".format(size_mb)

            self.form.maximumFileUploadSizeValue.setText(size_text)
        else:
            self.form.maximumFileUploadSizeValue.setText("Unknown")

    def clear_server_info(self):
        self.form.serverVersionValue.setText("—")
        self.form.messagingProtocolVersionValue.setText("—")
        self.form.maximumFileUploadSizeValue.setText("—")


# ------------------------------------------------------------
# Standalone login dialog
# ------------------------------------------------------------

_dialog = None
_login_panel = None


def show_login_dialog():
    """Open the standalone login dialog."""

    global _dialog, _login_panel

    # Reuse the existing dialog if it is already open.
    if _dialog is not None:
        _dialog.show()
        _dialog.raise_()
        _dialog.activateWindow()
        return

    _dialog = QtWidgets.QDialog()
    _dialog.setWindowTitle("Parts Manager PLM Login")

    _login_panel = LoginPanel(connection)

    layout = QtWidgets.QVBoxLayout(_dialog)
    layout.addWidget(_login_panel.form)

    _dialog.resize(450, 350)
    _dialog.finished.connect(_on_dialog_finished)

    _dialog.show()


def _on_dialog_finished(result):
    global _dialog, _login_panel

    _dialog = None
    _login_panel = None


# ------------------------------------------------------------
# FreeCAD command
# ------------------------------------------------------------

class CommandPMPLMLogin:

    def GetResources(self):
        return {
            "Pixmap": os.path.join(
                ICON_DIR,
                "login.svg"
            ),
            "MenuText": "Login",
            "ToolTip": "Connect to the Parts Manager PLM server"
        }

    def IsActive(self):
        return True

    def Activated(self):
        # Keep your existing login dialog implementation here.
        pass



    def IsActive(self):
        return True

    def Activated(self):
        show_login_dialog()


FreeCADGui.addCommand("PMPLM_Login",CommandPMPLMLogin())