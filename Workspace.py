# -*- coding: utf-8 -*-

"""
Parts Manager PLM - Workspace management

Features:
- Manage multiple workspace directories.
- Create new workspaces.
- Set the active FreeCAD working directory.
- List local FreeCAD parts.
- Display the latest version recorded on the PLM server.
"""

import os
import json

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets

import Login


ICON_DIR = os.path.join(
    FreeCAD.getUserAppDataDir(),
    "Mod",
    "part-manager-plm_for_freecad",
    "icons"
)

WORKSPACE_INVENTORY_ENDPOINT = "/plmJson/workspaceParts"


class WorkspacePanel:
    """Workspace management dialog."""

    def __init__(self):
        self.connection = Login.get_connection()

        self.settings = QtCore.QSettings(
            QtCore.QSettings.IniFormat,
            QtCore.QSettings.UserScope,
            "PMPLM",
            "PartsManager"
        )

        self.workspaces = []
        self.current_workspace = ""

        self.dialog = QtWidgets.QDialog()
        self.dialog.setWindowTitle("Parts Manager - Workspace")
        self.dialog.resize(650, 450)

        self.build_ui()
        self.load_workspaces()

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout(self.dialog)

        # Workspace selection
        workspace_layout = QtWidgets.QHBoxLayout()

        workspace_layout.addWidget(
            QtWidgets.QLabel("Workspace:")
        )

        self.workspace_combo = QtWidgets.QComboBox()
        self.workspace_combo.setMinimumWidth(250)
        self.workspace_combo.currentIndexChanged.connect(
            self.workspace_changed
        )

        workspace_layout.addWidget(
            self.workspace_combo, 1
        )

        self.create_workspace_button = QtWidgets.QPushButton(
            "Create Workspace"
        )
        self.create_workspace_button.clicked.connect(
            self.create_workspace
        )

        workspace_layout.addWidget(
            self.create_workspace_button
        )

        layout.addLayout(workspace_layout)

        # Active workspace path
        self.workspace_path_label = QtWidgets.QLabel(
            "Workspace directory: Not selected"
        )
        self.workspace_path_label.setWordWrap(True)

        layout.addWidget(self.workspace_path_label)

        # Workspace actions
        action_layout = QtWidgets.QHBoxLayout()

        self.set_workspace_button = QtWidgets.QPushButton(
            "Set as Active Workspace"
        )
        self.set_workspace_button.clicked.connect(
            self.set_active_workspace
        )

        action_layout.addWidget(
            self.set_workspace_button
        )

        self.refresh_button = QtWidgets.QPushButton(
            "Refresh"
        )
        self.refresh_button.clicked.connect(
            self.refresh_parts
        )

        action_layout.addWidget(
            self.refresh_button
        )

        layout.addLayout(action_layout)

        # Parts table
        self.parts_table = QtWidgets.QTableWidget()
        self.parts_table.setColumnCount(3)

        self.parts_table.setHorizontalHeaderLabels([
            "Local Part",
            "Server Version",
            "PLM Status"
        ])

        self.parts_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )

        self.parts_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )

        self.parts_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )

        self.parts_table.setAlternatingRowColors(True)

        header = self.parts_table.horizontalHeader()

        header.setSectionResizeMode( 0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode( 1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode( 2, QtWidgets.QHeaderView.ResizeToContents)

        layout.addWidget(self.parts_table, 1)

        # Status
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        layout.addWidget(self.status_label)

        # Close
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.dialog.close)

        layout.addWidget(close_button)

    # ---------------------------------------------------------
    # Workspace settings
    # ---------------------------------------------------------

    def load_workspaces(self):
        """Load saved workspaces without performing a refresh."""

        saved_workspaces = self.settings.value("workspaces", []) or []

        # QSettings may return a string instead of a list.
        if isinstance(saved_workspaces, str):
            saved_workspaces = [saved_workspaces]

        self.workspaces = []
        for path in saved_workspaces:
            if not path:
                continue

            path = os.path.abspath(os.path.expanduser(str(path)))

            if path not in self.workspaces:
                self.workspaces.append(path)

        saved_workspace = str(
            self.settings.value("workspace", "") or ""
        )
        saved_workspace = os.path.abspath(
            os.path.expanduser(saved_workspace)
        ) if saved_workspace else ""

        self.workspace_combo.blockSignals(True)
        self.workspace_combo.clear()

        for path in self.workspaces:
            self.workspace_combo.addItem(
                os.path.basename(path) or path,
                path
            )

        index = self.workspace_combo.findData(saved_workspace)

        if index >= 0:
            self.workspace_combo.setCurrentIndex(index)
        elif self.workspace_combo.count() > 0:
            self.workspace_combo.setCurrentIndex(0)

        self.workspace_combo.blockSignals(False)

        workspace_path = self.workspace_combo.currentData()

        if workspace_path and os.path.isdir(str(workspace_path)):
            self.current_workspace = str(workspace_path)

            self.workspace_path_label.setText(
                "Workspace directory: {}".format(
                    self.current_workspace
                )
            )

            self.status_label.setText(
                "Workspace loaded. Click Refresh to retrieve parts."
            )
        else:
            self.current_workspace = ""

            self.workspace_path_label.setText(
                "Workspace directory: Not selected"
            )

            self.status_label.setText(
                "Create or select a workspace to get started."
            )

        # Do not call refresh_parts() here.
        self.parts_table.setRowCount(0)

    def save_workspaces(self):
        """Persist the list of workspace directories."""

        self.settings.setValue(
            "workspaces",
            self.workspaces
        )

        self.settings.sync()

    def create_workspace(self):
        """Create a new workspace directory."""

        parent_directory = QtWidgets.QFileDialog.getExistingDirectory(
            self.dialog,
            "Select Parent Directory for Workspace",
            os.path.expanduser("~")
        )

        if not parent_directory:
            return

        workspace_name, accepted = (
            QtWidgets.QInputDialog.getText(
                self.dialog,
                "Create Workspace",
                "Workspace name:"
            )
        )

        if not accepted:
            return

        workspace_name = workspace_name.strip()

        if not workspace_name:
            self.show_error(
                "Please enter a workspace name."
            )
            return

        # Prevent a name from creating a directory outside
        # the selected parent directory.
        if (
            workspace_name in (".", "..")
            or os.path.basename(workspace_name) != workspace_name
            or "/" in workspace_name
            or "\\" in workspace_name
        ):
            self.show_error(
                "Please enter a valid workspace name."
            )
            return

        workspace_path = os.path.abspath(
            os.path.join(
                parent_directory,
                workspace_name
            )
        )

        if os.path.exists(workspace_path):
            if not os.path.isdir(workspace_path):
                self.show_error(
                    "A file with that name already exists."
                )
                return

            answer = QtWidgets.QMessageBox.question(
                self.dialog,
                "Workspace Exists",
                "This directory already exists.\n"
                "Use it as a workspace?",
                QtWidgets.QMessageBox.Yes
                | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )

            if answer != QtWidgets.QMessageBox.Yes:
                return

        else:
            try:
                os.makedirs(workspace_path)

            except OSError as exc:
                self.show_error(
                    "Could not create workspace:\n{}".format(exc)
                )
                return

        if workspace_path not in self.workspaces:
            self.workspaces.append(workspace_path)

        self.save_workspaces()

        self.workspace_combo.addItem(
            workspace_name,
            workspace_path
        )

        self.workspace_combo.setCurrentIndex(
            self.workspace_combo.count() - 1
        )

        self.set_active_workspace()

    def workspace_changed(self, *_args):
        """Handle workspace selection without blocking the UI."""

        workspace_path = self.workspace_combo.currentData()

        if not workspace_path:
            self.current_workspace = ""

            self.workspace_path_label.setText(
                "Workspace directory: Not selected"
            )

            self.parts_table.setRowCount(0)

            self.status_label.setText(
                "Please select a workspace."
            )
            return

        self.current_workspace = str(workspace_path)

        self.workspace_path_label.setText(
            "Workspace directory: {}".format(
                self.current_workspace
            )
        )

        self.parts_table.setRowCount(0)

        self.status_label.setText(
            "Workspace selected. Click Refresh to load parts."
        )
    def set_active_workspace(self):
        """Set the selected directory as FreeCAD's working directory."""

        workspace_path = self.workspace_combo.currentData()

        if not workspace_path:
            self.show_error(
                "Please select a workspace first."
            )
            return

        workspace_path = os.path.abspath(
            str(workspace_path)
        )

        if not os.path.isdir(workspace_path):
            self.show_error(
                "The workspace directory does not exist:\n"
                + workspace_path
            )
            return

        try:
            # FreeCAD's general file-open/save preferences.
            preferences = FreeCAD.ParamGet(
                "User parameter:BaseApp/Preferences/General"
            )

            preferences.SetString(
                "WorkingDir",
                workspace_path
            )

            preferences.SetString(
                "FileOpenSavePath",
                workspace_path
            )

            # Save the selected workspace for this workbench.
            self.settings.setValue(
                "workspace",
                workspace_path
            )

            self.settings.sync()

            self.current_workspace = workspace_path

            self.workspace_path_label.setText(
                "Workspace directory: {}".format(
                    workspace_path
                )
            )

            self.status_label.setText(
                "Active workspace set to {}".format(
                    workspace_path
                )
            )

            self.refresh_parts()

        except Exception as exc:
            self.show_error(
                "Could not set the active workspace:\n{}".format(
                    exc
                )
            )

    # ---------------------------------------------------------
    # Local parts
    # ---------------------------------------------------------

    def find_local_parts(self):
        """
        Find local FreeCAD documents.

        Returns paths relative to the workspace root.
        Subdirectories are included.
        """

        workspace_path = self.current_workspace

        if (
            not workspace_path
            or not os.path.isdir(workspace_path)
        ):
            return []

        parts = []

        for root, _dirs, files in os.walk(workspace_path):
            for filename in files:
                if filename.lower().endswith(".fcstd"):
                    absolute_path = os.path.join(
                        root,
                        filename
                    )

                    relative_path = os.path.relpath(
                        absolute_path,
                        workspace_path
                    )

                    parts.append(relative_path)

        return sorted(
            parts,
            key=lambda value: value.lower()
        )

    # ---------------------------------------------------------
    # Server inventory
    # ---------------------------------------------------------

    def get_server_inventory(self, local_parts):
        """
        Retrieve PLM status for local workspace parts.

        POST /plmJson/workspaceParts

        Request:
            {
                "parts": [
                    {
                        "name": "bracket.FCStd",
                        "relativePath": "bracket.FCStd"
                    }
                ]
            }

        Response:
            {
                "parts": [
                    {
                        "name": "bracket.FCStd",
                        "relativePath": "bracket.FCStd",
                        "existsInPlm": true,
                        "plmPartId": 123,
                        "latestVersion": 3,
                        "plmStatus": "CREATED"
                    }
                ]
            }
        """

        if not self.connection.connected:
            raise RuntimeError(
                "Not connected to the PLM server. "
                "Please connect using the Login module."
            )

        if not self.connection.url:
            raise RuntimeError(
                "The PLM server URL is not configured."
            )

        url = (
                self.connection.url.rstrip("/")
                + WORKSPACE_INVENTORY_ENDPOINT
        )

        # Send relative paths so the server can identify each local part.
        request_parts = []

        for relative_path in local_parts:
            request_parts.append({
                "name": os.path.basename(relative_path),
                "relativePath": relative_path.replace("\\", "/")
            })

        response = self.connection.session.post(
            url,
            json={
                "parts": request_parts
            },
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise RuntimeError(
                "Unexpected workspace parts response."
            )

        server_parts = data.get("parts", [])

        inventory = {}

        for part in server_parts:
            if not isinstance(part, dict):
                continue

            name = str(part.get("name") or "")
            relative_path = str(
                part.get("relativePath") or ""
            )

            # Normalize paths for consistent matching.
            normalized_path = relative_path.replace(
                "\\", "/"
            ).lower()

            if not normalized_path and name:
                normalized_path = name.replace(
                    "\\", "/"
                ).lower()

            latest_version = part.get("latestVersion")

            if latest_version is None:
                latest_version = "—"

            entry = {
                "version": str(latest_version),
                "exists": part.get("existsInPlm", False),
                "status": part.get("plmStatus", ""),
                "plmPartId": part.get("plmPartId"),
                "part": part
            }

            if normalized_path:
                inventory[normalized_path] = entry

            # Also index by filename for compatibility with lookups
            # that do not have a matching relative path.
            if name:
                filename_key = os.path.basename(
                    name.replace("\\", "/")
                ).lower()

                inventory.setdefault(
                    filename_key,
                    entry
                )

        return inventory
    # ---------------------------------------------------------
    # Refresh table
    # ---------------------------------------------------------

    def refresh_parts(self):
        """Refresh the local parts table and server versions."""

        if not self.current_workspace:
            self.parts_table.setRowCount(0)
            self.status_label.setText(
                "Please select a workspace."
            )
            return

        local_parts = self.find_local_parts()

        self.refresh_button.setEnabled(False)
        self.status_label.setText(
            "Scanning local parts..."
        )


        try:
            inventory = self.get_server_inventory(local_parts)

        except Exception as exc:
            inventory = None
            server_error = str(exc)

        self.parts_table.setRowCount(len(local_parts))

        for row, relative_path in enumerate(local_parts):
            local_item = QtWidgets.QTableWidgetItem(
                relative_path
            )

            local_item.setToolTip(
                os.path.join(
                    self.current_workspace,
                    relative_path
                )
            )

            self.parts_table.setItem(
                row,
                0,
                local_item
            )

            version_text = "Unknown"

            if inventory is not None:
                normalized_path = (
                    relative_path.replace("\\", "/").lower()
                )

                filename = os.path.basename(
                    relative_path
                ).lower()

                server_part = inventory.get(
                    normalized_path
                )

                if server_part is None:
                    server_part = inventory.get(filename)

                if server_part is None:
                    version_text = "Not in PLM"

                else:
                    version_text = server_part["version"]

            version_item = QtWidgets.QTableWidgetItem(
                version_text
            )

            self.parts_table.setItem(
                row,
                1,
                version_item
            )

            # PLM status
            status_text = "Unknown"

            if inventory is not None:
                normalized_path = (
                    relative_path.replace("\\", "/").lower()
                )

                filename = os.path.basename(
                    relative_path
                ).lower()

                server_part = inventory.get(normalized_path)

                if server_part is None:
                    server_part = inventory.get(filename)

                if server_part is None:
                    status_text = "NOT_IN_PLM"

                else:
                    status_text = (
                            server_part.get("status") or "Unknown"
                    )

            status_item = QtWidgets.QTableWidgetItem(
                str(status_text)
            )

            self.parts_table.setItem(
                row,
                2,
                status_item
            )

        self.refresh_button.setEnabled(True)

        if inventory is None:
            self.status_label.setText(
                "Found {} local part(s). "
                "Could not retrieve server versions: {}".format(
                    len(local_parts),
                    server_error
                )
            )

        else:
            self.status_label.setText(
                "Found {} local part(s). "
                "Server inventory refreshed.".format(
                    len(local_parts)
                )
            )

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def show_error(self, message):
        QtWidgets.QMessageBox.warning(
            self.dialog,
            "Parts Manager Workspace",
            message
        )

    def show(self):
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()


# -------------------------------------------------------------
# FreeCAD command
# -------------------------------------------------------------

_workspace_panel = None


def show_workspace():
    global _workspace_panel

    if _workspace_panel is None:
        _workspace_panel = WorkspacePanel()

    _workspace_panel.show()


class CommandPMPLMWorkspace:

    def GetResources(self):
        return {
            "Pixmap": os.path.join(
                ICON_DIR,
                "workspace.svg"
            ),
            "MenuText": "Workspace",
            "ToolTip": "Workspace Manager Parts Manager PLM server"
        }
    def IsActive(self):
        return True

    def Activated(self):
        show_workspace()


FreeCADGui.addCommand("PMPLM_Workspace",CommandPMPLMWorkspace())