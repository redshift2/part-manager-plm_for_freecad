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
import shutil
import FreeCAD
import FreeCADGui
import Login
import WorkspaceInventory
import PlmDownload
import PlmTags

from PySide import QtGui
from PySide import QtCore, QtGui, QtWidgets

WORKSPACE_INVENTORY_ENDPOINT = "/plmJson/workspaceParts"

ICON_DIR = os.path.join(
    FreeCAD.getUserAppDataDir(),
    "Mod",
    "part-manager-plm_for_freecad",
    "icons"
)



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
        self.dialog.resize(1100, 520)

        self.build_ui()
        self.load_workspaces()
        self.refresh_parts()

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout(self.dialog)

        # Workspace selection
        workspace_layout = QtWidgets.QHBoxLayout()
        workspace_layout.addWidget(QtWidgets.QLabel("Workspace:"))

        self.workspace_combo = QtWidgets.QComboBox()
        self.workspace_combo.setMinimumWidth(250)
        self.workspace_combo.currentIndexChanged.connect(self.workspace_changed)
        workspace_layout.addWidget(self.workspace_combo, 1)

        self.create_workspace_button = QtWidgets.QPushButton("Create Workspace")
        self.create_workspace_button.clicked.connect(self.create_workspace)
        workspace_layout.addWidget(self.create_workspace_button)

        layout.addLayout(workspace_layout)

        # Active workspace path
        self.workspace_path_label = QtWidgets.QLabel("Workspace directory: Not selected")
        self.workspace_path_label.setWordWrap(True)
        layout.addWidget(self.workspace_path_label)

        # Workspace actions
        action_layout = QtWidgets.QHBoxLayout()

        self.set_workspace_button = QtWidgets.QPushButton( "Set as Active Workspace")
        self.set_workspace_button.clicked.connect( self.set_active_workspace)
        action_layout.addWidget(self.set_workspace_button)

        self.delete_workspace_button = QtWidgets.QPushButton( "Delete Workspace")
        self.delete_workspace_button.clicked.connect( self.delete_workspace)
        action_layout.addWidget(self.delete_workspace_button)

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_parts)
        action_layout.addWidget(self.refresh_button)


        action_layout.addStretch()
        layout.addLayout(action_layout)

        # Parts table
        self.parts_table = QtWidgets.QTableWidget()
        self.parts_table.setColumnCount(6)
        self.parts_table.setHorizontalHeaderLabels([
            "Local Part",
            "Local Version",
            "CAD Version",
            "Lifecycle State",
            "Checked Out By",
            "Tags"
        ])

        self.parts_table.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.parts_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self.parts_table.setAlternatingRowColors(True)

        header = self.parts_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch )
        header.setSectionResizeMode( 1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode( 2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode( 3, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode( 4, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode( 5, QtWidgets.QHeaderView.Stretch )

        layout.addWidget(self.parts_table, 1)

        # -----------------------------------------------------
        # Workspace actions - icon toolbar
        # -----------------------------------------------------

        table_action_layout = QtWidgets.QHBoxLayout()

        table_action_layout.setSpacing(6)

        # Import to Workspace
        self.import_button = self.create_icon_button(
            "import.svg",
            "Import files into workspace",
            self.import_to_workspace
        )

        table_action_layout.addWidget(
            self.import_button
        )

        # Sync with Server
        self.sync_button = self.create_icon_button(
            "sync.svg",
            "Synchronize workspace with PLM server",
            self.sync_with_server
        )

        table_action_layout.addWidget(
            self.sync_button
        )

        # Remove from Workspace
        self.remove_workspace_button = self.create_icon_button(
            "remove.svg",
            "Remove selected parts from workspace",
            self.remove_from_workspace
        )

        table_action_layout.addWidget(
            self.remove_workspace_button
        )

        # Open in FreeCAD
        self.open_freecad_button = self.create_icon_button(
            "open.svg",
            "Open selected parts in FreeCAD",
            self.open_in_freecad
        )

        table_action_layout.addWidget(
            self.open_freecad_button
        )

        # Check Out selected PLM parts
        self.checkout_button = self.create_icon_button(
            "checkout.svg",
            "Check out selected PLM parts to your account",
            self.check_out_parts
        )
        # Provide a visible label if checkout.svg has not been installed.
        if not os.path.isfile(os.path.join(ICON_DIR, "checkout.svg")):
            self.checkout_button.setText("Out")
        table_action_layout.addWidget(self.checkout_button)

        # Check-In to PLM
        self.checkin_button = self.create_icon_button(
            "checkin.svg",
            "Check selected parts into PLM",
            self.check_in_to_plm
        )

        table_action_layout.addWidget(
            self.checkin_button
        )

        # Edit Tags
        self.edit_tags_button = self.create_icon_button(
            "tags.svg",
            "Edit tags for selected PLM parts",
            self.edit_part_tags
        )

        table_action_layout.addWidget(
            self.edit_tags_button
        )

        table_action_layout.addStretch()

        layout.addLayout(table_action_layout)
        layout.addLayout(table_action_layout)

        # Status
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Close
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.dialog.close)
        layout.addWidget(close_button)

    # ---------------------------------------------------------
    # Select PLM tags using hierarchical tree
    # ---------------------------------------------------------

    def select_plm_tags(self, selected_tags=None):
        """
        Display PLM tags in a hierarchical tree.

        Features:
        - Parent/child tag hierarchy.
        - Expand and collapse categories.
        - Multiple tag selection.
        - Independent checkboxes.
        - Returns selected tag IDs.
        """

        import PlmTags
        tags = PlmTags.get_tags(self.connection)
        if selected_tags is None:
            selected_tags = []

        selected_tags = {
            str(tag_id) for tag_id in selected_tags
        }
        try:
            tags = PlmTags.get_tags(self.connection)

        except Exception as exc:
            self.show_error(
                "Could not retrieve PLM tags:\n{}".format(exc)
            )
            return None

        dialog = QtWidgets.QDialog(self.dialog)
        dialog.setWindowTitle("Select PLM Tags")
        dialog.resize(450, 550)

        layout = QtWidgets.QVBoxLayout(dialog)

        layout.addWidget(
            QtWidgets.QLabel(
                "Select tags to assign to the uploaded parts:"
            )
        )

        # -----------------------------------------------------
        # Hierarchical tag tree
        # -----------------------------------------------------

        tag_tree = QtWidgets.QTreeWidget()

        tag_tree.setHeaderLabels(["PLM Tags"])
        tag_tree.setSelectionMode(
            QtWidgets.QAbstractItemView.NoSelection
        )

        tag_tree.setAlternatingRowColors(True)

        layout.addWidget(tag_tree)

        # -----------------------------------------------------
        # Create tag items
        # -----------------------------------------------------

        tag_items = {}
        tag_items_by_name = {}

        for tag in tags:

            tag_id = tag.get("id")
            tag_name = str(tag.get("name", "")).strip()

            if tag_id is None or not tag_name:
                continue

            tag_id = str(tag_id)

            item = QtWidgets.QTreeWidgetItem()

            item.setText(0, tag_name)

            item.setData(
                0,
                QtCore.Qt.UserRole,
                int(tag_id)
            )

            item.setFlags(
                item.flags()
                | QtCore.Qt.ItemIsUserCheckable
            )

            item.setCheckState(
                0,
                QtCore.Qt.Checked
                if tag_id in selected_tags
                else QtCore.Qt.Unchecked
            )

            # Store by ID for collecting selected tags.
            tag_items[tag_id] = item

            # Store by name for resolving parent relationships.
            tag_items_by_name[tag_name] = item

        # -----------------------------------------------------
        # Build parent-child hierarchy using parent NAME
        # -----------------------------------------------------

        for tag in tags:

            tag_id = tag.get("id")

            if tag_id is None:
                continue

            item = tag_items.get(str(tag_id))

            if item is None:
                continue

            # Parent is a tag name, not an ID.
            parent_name = tag.get("parent")

            if parent_name is not None:
                parent_name = str(parent_name).strip()

            parent_item = tag_items_by_name.get(parent_name)

            if parent_item is not None and parent_item is not item:

                parent_item.addChild(item)

                FreeCAD.Console.PrintMessage(
                    "PLM Tag: {} -> {}\n".format(
                        parent_item.text(0),
                        item.text(0)
                    )
                )

            else:

                tag_tree.addTopLevelItem(item)

                FreeCAD.Console.PrintMessage(
                    "PLM Root Tag: {}\n".format(
                        item.text(0)
                    )
                )



        # -----------------------------------------------------
        # Expand tree
        # -----------------------------------------------------

        tag_tree.expandToDepth(1)

        tag_tree.resizeColumnToContents(0)

        # -----------------------------------------------------
        # Expand / Collapse buttons
        # -----------------------------------------------------

        tree_buttons = QtWidgets.QHBoxLayout()

        expand_button = QtWidgets.QPushButton(
            "Expand All"
        )

        expand_button.clicked.connect(
            tag_tree.expandAll
        )

        tree_buttons.addWidget(expand_button)

        collapse_button = QtWidgets.QPushButton(
            "Collapse All"
        )

        collapse_button.clicked.connect(
            tag_tree.collapseAll
        )

        tree_buttons.addWidget(collapse_button)

        tree_buttons.addStretch()

        layout.addLayout(tree_buttons)

        # -----------------------------------------------------
        # OK / Cancel
        # -----------------------------------------------------

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok
            | QtWidgets.QDialogButtonBox.Cancel
        )

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None

        # -----------------------------------------------------
        # Collect checked tags
        # -----------------------------------------------------

        selected_tag_ids = []

        for item in tag_items.values():

            if item.checkState(0) == QtCore.Qt.Checked:

                tag_id = item.data(
                    0,
                    QtCore.Qt.UserRole
                )

                selected_tag_ids.append(
                    int(tag_id)
                )

        return selected_tag_ids

    def create_icon_button(self, icon_name, tooltip, callback):
        """
        Create an icon-only toolbar button.
        """

        button = QtWidgets.QPushButton()

        icon_path = os.path.join(
            ICON_DIR,
            icon_name
        )

        button.setIcon(
            QtGui.QIcon(icon_path)
        )

        button.setIconSize(
            QtCore.QSize(28, 28)
        )

        button.setFixedSize(42, 42)

        button.setToolTip(tooltip)

        button.clicked.connect(callback)

        return button
    # ---------------------------------------------------------
    # Edit tags assigned to selected workspace parts
    # ---------------------------------------------------------

    def edit_part_tags(self):
        """
        Edit PLM tags for selected workspace parts.

        Features:
        - Supports one or multiple selected parts.
        - Loads existing tags from the server.
        - Opens the hierarchical tag selection dialog.
        - Saves tags using PlmTags.set_part_tags().
        - Refreshes the workspace table.
        """

        # -----------------------------------------------------
        # Verify connection
        # -----------------------------------------------------

        self.connection = Login.get_connection()

        if not self.connection or not self.connection.connected:
            self.show_error(
                "Please connect to the PLM server first."
            )
            return

        # -----------------------------------------------------
        # Get selected workspace parts
        # -----------------------------------------------------

        selected_rows = sorted({
            index.row()
            for index in self.parts_table.selectionModel().selectedRows()
        })

        if not selected_rows:
            self.show_error(
                "Please select one or more parts to edit tags."
            )
            return

        relative_paths = []

        for row in selected_rows:

            item = self.parts_table.item(row, 0)

            if item is None:
                continue

            relative_paths.append(
                item.text().replace("\\", "/")
            )

        if not relative_paths:
            return

        # -----------------------------------------------------
        # Retrieve server inventory
        # -----------------------------------------------------

        try:

            server_inventory = self.get_server_inventory(
                relative_paths
            )

        except Exception as exc:

            self.show_error(
                "Could not retrieve PLM part information:\n\n{}".format(
                    exc
                )
            )
            return

        # -----------------------------------------------------
        # Resolve selected PLM parts
        # -----------------------------------------------------

        selected_parts = []
        errors = []

        for relative_path in relative_paths:

            key = relative_path.lower()

            server_part = (
                server_inventory.get(key)
                or server_inventory.get(
                    os.path.basename(key)
                )
            )

            if not server_part or not server_part.get("exists"):

                errors.append(
                    "{}: Not found in PLM".format(
                        relative_path
                    )
                )
                continue

            part_id = server_part.get("plmPartId")

            if part_id is None:

                errors.append(
                    "{}: Missing PLM part ID".format(
                        relative_path
                    )
                )
                continue

            selected_parts.append({
                "name": relative_path,
                "part_id": part_id,
                "tags": server_part.get("tags", [])
            })

        if not selected_parts:

            self.show_error(
                "None of the selected parts exists in PLM."
            )
            return

        # -----------------------------------------------------
        # Retrieve available tags
        # -----------------------------------------------------

        try:

            available_tags = PlmTags.get_tags(
                self.connection
            )

        except Exception as exc:

            self.show_error(
                "Could not retrieve PLM tags:\n\n{}".format(
                    exc
                )
            )
            return

        # Map tag names to tag IDs.
        tag_name_to_id = {}

        for tag in available_tags:

            tag_name = str(
                tag.get("name", "")
            ).strip()

            tag_id = tag.get("id")

            if tag_name and tag_id is not None:

                tag_name_to_id[tag_name] = int(tag_id)

        # -----------------------------------------------------
        # Determine currently assigned tags
        # -----------------------------------------------------

        # For a single selected part, preselect its tags.
        # For multiple parts, preselect only tags common to all.
        #
        # The chosen tags will replace the tags on every
        # selected part.

        existing_tag_sets = []

        for part in selected_parts:

            existing_ids = set()

            for tag in part["tags"]:

                if isinstance(tag, dict):

                    tag_id = tag.get("id")

                    if tag_id is not None:
                        existing_ids.add(int(tag_id))
                        continue

                    tag_name = str(
                        tag.get("name", "")
                    )

                else:

                    tag_name = str(tag)

                tag_id = tag_name_to_id.get(
                    tag_name
                )

                if tag_id is not None:
                    existing_ids.add(tag_id)

            existing_tag_sets.append(existing_ids)

        selected_tag_ids = []

        if existing_tag_sets:

            common_tags = set.intersection(
                *existing_tag_sets
            )

            selected_tag_ids = sorted(
                common_tags
            )

        # -----------------------------------------------------
        # Open tag selection dialog
        # -----------------------------------------------------

        tag_ids = self.select_plm_tags(
            selected_tags=selected_tag_ids
        )

        if tag_ids is None:
            return

        # -----------------------------------------------------
        # Confirm changes
        # -----------------------------------------------------

        part_names = "\n".join(
            part["name"]
            for part in selected_parts
        )

        answer = QtWidgets.QMessageBox.question(
            self.dialog,
            "Edit PLM Tags",
            "Replace the tags assigned to the following "
            "{} part(s)?\n\n"
            "{}\n\n"
            "Selected tags: {}\n\n"
            "This will replace the existing tags on "
            "each selected part.".format(
                len(selected_parts),
                part_names,
                len(tag_ids)
            ),
            QtWidgets.QMessageBox.Yes
            | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if answer != QtWidgets.QMessageBox.Yes:
            return

        # -----------------------------------------------------
        # Update tags on server
        # -----------------------------------------------------

        updated_count = 0

        self.edit_tags_button.setEnabled(False)

        try:

            for part in selected_parts:

                try:

                    PlmTags.set_part_tags(
                        part_id=part["part_id"],
                        tag_ids=tag_ids,
                        connection=self.connection
                    )

                    updated_count += 1

                    FreeCAD.Console.PrintMessage(
                        "PLM: Updated tags {} for part {}\n".format(
                            tag_ids,
                            part["part_id"]
                        )
                    )

                except Exception as exc:

                    errors.append(
                        "{}: {}".format(
                            part["name"],
                            exc
                        )
                    )

        finally:

            self.edit_tags_button.setEnabled(True)

        # -----------------------------------------------------
        # Refresh workspace table
        # -----------------------------------------------------

        self.refresh_parts()

        # -----------------------------------------------------
        # Display result
        # -----------------------------------------------------

        summary = (
            "Updated tags for {} part(s).".format(
                updated_count
            )
        )

        if errors:

            summary += (
                "\n\nThe following parts could not "
                "be updated:\n\n"
                + "\n".join(errors)
            )

            QtWidgets.QMessageBox.warning(
                self.dialog,
                "Edit PLM Tags",
                summary
            )

        else:

            QtWidgets.QMessageBox.information(
                self.dialog,
                "Edit PLM Tags",
                summary
            )

        self.status_label.setText(
            "Tags updated for {} part(s).".format(
                updated_count
            )
        )
    # ---------------------------------------------------------
    # Check out selected PLM parts
    # ---------------------------------------------------------

    def check_out_parts(self):
        """Check out selected server parts using the current PLM login."""
        import plmupload

        self.connection = Login.get_connection()
        if not self.connection or not self.connection.connected:
            self.show_error("Please connect to the PLM server first.")
            return

        rows = sorted({
            index.row()
            for index in self.parts_table.selectionModel().selectedRows()
        })
        if not rows:
            self.show_error("Select one or more parts to check out.")
            return

        paths = []
        for row in rows:
            item = self.parts_table.item(row, 0)
            if item is not None:
                paths.append(item.text().replace("\\", "/"))
        if not paths:
            return

        try:
            inventory = self.get_server_inventory(paths)
        except Exception as exc:
            self.show_error("Could not retrieve server inventory:\n{}".format(exc))
            return

        eligible = []
        skipped = []
        seen_ids = set()
        for path in paths:
            key = path.lower()
            entry = inventory.get(key) or inventory.get(os.path.basename(key))
            if not entry or not entry.get("exists"):
                skipped.append("{}: not in PLM".format(path))
                continue
            part_id = entry.get("plmPartId")
            if part_id is None:
                skipped.append("{}: missing PLM part ID".format(path))
                continue
            if entry.get("canCheckOut") is False or (
                entry.get("part", {}).get("canCheckOut") is False
            ):
                skipped.append("{}: checkout not permitted (state: {}, owner: {})".format(
                    path, entry.get("status"), entry.get("checkedOutBy") or "none"))
                continue
            if part_id not in seen_ids:
                seen_ids.add(part_id)
                eligible.append((path, part_id))

        if not eligible:
            self.show_error("No selected parts can be checked out.\n\n" +
                            "\n".join(skipped))
            return

        answer = QtWidgets.QMessageBox.question(
            self.dialog, "Check Out Parts",
            "Check out {} part(s) to your PLM account?\n\n{}".format(
                len(eligible), "\n".join(path for path, _ in eligible)),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return

        completed = []
        errors = list(skipped)
        self.checkout_button.setEnabled(False)
        try:
            uploader = plmupload.PlmUploader(connection=self.connection)
            for path, part_id in eligible:
                try:
                    result = uploader.check_out_part(part_id)
                    completed.append(path)
                    FreeCAD.Console.PrintMessage(
                        "PLM: Checked out {} (ID {}): {}\n".format(
                            path, part_id, result.get("lifecycleState", "CHECKED_OUT")))
                except Exception as exc:
                    errors.append("{}: {}".format(path, exc))
        finally:
            self.checkout_button.setEnabled(True)
            self.refresh_parts()

        summary = "Checked out {} part(s).".format(len(completed))
        if errors:
            summary += "\n\nSkipped or failed:\n" + "\n".join(errors)
            QtWidgets.QMessageBox.warning(self.dialog, "Check Out Parts", summary)
        else:
            QtWidgets.QMessageBox.information(self.dialog, "Check Out Parts", summary)
        self.status_label.setText(summary)

    # ---------------------------------------------------------
    # Check selected workspace parts into PLM
    # ---------------------------------------------------------

    def check_in_to_plm(self):
        """
        Upload selected workspace parts using plmupload.py.

        Features:
        - Supports multiple selected files.
        - Opens documents if necessary.
        - Reuses already open documents.
        - Prompts to save modified documents.
        - Uses plmupload.PlmUploader.
        - Refreshes workspace inventory after upload.
        """

        import plmupload

        # Verify PLM connection.
        self.connection = Login.get_connection()

        if not self.connection or not self.connection.connected:
            self.show_error(
                "Please connect to the PLM server first."
            )
            return

        # Verify workspace.
        workspace = self.current_workspace

        if not workspace or not os.path.isdir(workspace):
            self.show_error(
                "Please select a valid workspace first."
            )
            return

        workspace = os.path.realpath(workspace)

        # Get selected rows.
        selected_rows = sorted({
            index.row()
            for index in self.parts_table.selectionModel().selectedRows()
        })

        if not selected_rows:
            self.show_error(
                "Please select one or more parts to check in."
            )
            return

        documents = []
        errors = []
        seen_paths = set()

        # -----------------------------------------------------
        # Collect selected FreeCAD documents
        # -----------------------------------------------------

        for row in selected_rows:

            item = self.parts_table.item(row, 0)

            if item is None:
                continue

            relative_path = item.text()

            file_path = os.path.realpath(
                os.path.join(
                    workspace,
                    relative_path
                )
            )

            # Validate workspace path.
            try:
                if os.path.commonpath(
                    [workspace, file_path]
                ) != workspace:

                    errors.append(
                        "Invalid workspace path: {}".format(
                            relative_path
                        )
                    )
                    continue

            except ValueError:
                errors.append(
                    "Invalid workspace path: {}".format(
                        relative_path
                    )
                )
                continue

            if not os.path.isfile(file_path):
                errors.append(
                    "File not found: {}".format(
                        relative_path
                    )
                )
                continue

            if not file_path.lower().endswith(".fcstd"):
                errors.append(
                    "Not a FreeCAD document: {}".format(
                        relative_path
                    )
                )
                continue

            if file_path in seen_paths:
                continue

            seen_paths.add(file_path)

            try:
                # Find document if already open.
                doc = None

                for existing_doc in FreeCAD.listDocuments().values():

                    existing_path = getattr(
                        existing_doc,
                        "FileName",
                        ""
                    )

                    if not existing_path:
                        continue

                    if os.path.realpath(existing_path) == file_path:
                        doc = existing_doc
                        break

                # Open document if not already open.
                if doc is None:

                    FreeCAD.Console.PrintMessage(
                        "PLM: Opening for check-in: {}\n".format(
                            file_path
                        )
                    )

                    doc = FreeCAD.openDocument(file_path)

                if doc is None:
                    raise RuntimeError(
                        "Could not open FreeCAD document."
                    )

                documents.append(doc)

            except Exception as exc:

                errors.append(
                    "{}: {}".format(
                        relative_path,
                        exc
                    )
                )

        # -----------------------------------------------------
        # Verify documents
        # -----------------------------------------------------

        if errors:
            QtWidgets.QMessageBox.warning(
                self.dialog,
                "Check-In to PLM",
                "Some documents could not be prepared:\n\n"
                + "\n".join(errors)
                + "\n\nNo files have been uploaded."
            )
            return

        if not documents:
            self.show_error(
                "No valid documents were selected for check-in."
            )
            return

        # -----------------------------------------------------
        # Save modified documents
        # -----------------------------------------------------

        modified_documents = [
            doc for doc in documents
            if getattr(doc, "Modified", False)
        ]

        if modified_documents:

            names = "\n".join(
                doc.Label for doc in modified_documents
            )

            answer = QtWidgets.QMessageBox.question(
                self.dialog,
                "Save Documents",
                "The following documents have unsaved changes:\n\n"
                "{}\n\n"
                "Save these documents before check-in?".format(
                    names
                ),
                QtWidgets.QMessageBox.Yes
                | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Yes
            )

            if answer != QtWidgets.QMessageBox.Yes:
                return

            try:
                for doc in modified_documents:
                    doc.save()

            except Exception as exc:
                self.show_error(
                    "Could not save document:\n{}".format(exc)
                )
                return

        # -----------------------------------------------------
        # Confirm check-in
        # -----------------------------------------------------

        names = "\n".join(
            doc.Label for doc in documents
        )

        answer = QtWidgets.QMessageBox.question(
            self.dialog,
            "Check-In to PLM",
            "Check in the following {} document(s)?\n\n"
            "{}".format(
                len(documents),
                names
            ),
            QtWidgets.QMessageBox.Yes
            | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if answer != QtWidgets.QMessageBox.Yes:
            return

        # -----------------------------------------------------
        # Upload using plmupload.py
        # -----------------------------------------------------

        self.checkin_button.setEnabled(False)

        self.status_label.setText(
            "Uploading {} document(s) to PLM...".format(
                len(documents)
            )
        )

        QtWidgets.QApplication.processEvents()


        try:
            FreeCAD.Console.PrintMessage(
                "PLM: Starting workspace check-in.\n"
            )
            tag_ids = self.select_plm_tags()

            if tag_ids is None:
                return

            uploader = plmupload.PlmUploader(
                connection=self.connection,
                documents=documents
            )

            result = uploader.upload_documents(
                documents=documents
            )

            if result is False:
                raise RuntimeError(
                    "The PLM upload did not complete successfully."
                )

            FreeCAD.Console.PrintMessage(
                "PLM: Workspace check-in completed.\n"
            )

            self.status_label.setText(
                "Check-in complete: {} document(s).".format(
                    len(documents)
                )
            )

            QtWidgets.QMessageBox.information(
                self.dialog,
                "Check-In to PLM",
                "Successfully checked in {} document(s).".format(
                    len(documents)
                )
            )
            # Retrieve server inventory after upload.
            relative_paths = []

            for doc in documents:

                filename = getattr(doc, "FileName", "")

                if not filename:
                    continue

                relative_path = os.path.relpath(
                    filename,
                    self.current_workspace
                )

                relative_paths.append(relative_path)

            server_inventory = self.get_server_inventory(
                relative_paths
            )

            tag_errors = []

            for relative_path in relative_paths:

                key = relative_path.replace("\\", "/").lower()

                server_part = server_inventory.get(key)

                if server_part is None:
                    tag_errors.append(
                        "{}: Part not found on server".format(relative_path)
                    )
                    continue

                part_id = server_part.get("plmPartId")

                if part_id is None:
                    tag_errors.append(
                        "{}: Missing PLM part ID".format(relative_path)
                    )
                    continue

                try:
                    PlmTags.set_part_tags(
                        part_id=part_id,
                        tag_ids=tag_ids,
                        connection=self.connection
                    )

                    FreeCAD.Console.PrintMessage(
                        "PLM: Assigned tags {} to part {}\n".format(
                            tag_ids,
                            part_id
                        )
                    )
                    # Refresh after uploading and assigning tags.
                    self.refresh_parts()

                except Exception as exc:
                    tag_errors.append(
                        "{}: {}".format(relative_path, exc)
                    )

            if tag_errors:
                QtWidgets.QMessageBox.warning(
                    self.dialog,
                    "PLM Tag Assignment",
                    "The upload completed, but some tags could not "
                    "be assigned:\n\n"
                    + "\n".join(tag_errors)
                )
        except Exception as exc:

            FreeCAD.Console.PrintError(
                "PLM: Workspace check-in failed: {}\n".format(
                    exc
                )
            )

            self.show_error(
                "Check-in failed:\n\n{}".format(exc)
            )

        finally:
            self.checkin_button.setEnabled(True)
    # ---------------------------------------------------------
    # Open selected parts in FreeCAD
    # ---------------------------------------------------------

    def open_in_freecad(self):
        """
        Open selected workspace parts in FreeCAD.

        Features:
        - Supports multiple selected files.
        - Opens local FCStd files.
        - Reuses documents already open in FreeCAD.
        - Supports workspace subdirectories.
        - Activates the last opened document.
        """

        workspace = self.current_workspace

        if not workspace or not os.path.isdir(workspace):
            self.show_error(
                "Please select a valid workspace first."
            )
            return

        workspace = os.path.realpath(workspace)

        # Get selected rows.
        selected_rows = sorted({
            index.row()
            for index in self.parts_table.selectionModel().selectedRows()
        })

        if not selected_rows:
            self.show_error(
                "Please select one or more parts to open."
            )
            return

        opened_count = 0
        already_open_count = 0
        errors = []
        last_document = None

        for row in selected_rows:

            item = self.parts_table.item(row, 0)

            if item is None:
                continue

            relative_path = item.text()

            # Resolve the file path inside the workspace.
            file_path = os.path.realpath(
                os.path.join(
                    workspace,
                    relative_path
                )
            )

            # Prevent opening files outside the workspace.
            try:
                if os.path.commonpath(
                        [workspace, file_path]
                ) != workspace:
                    errors.append(
                        "Invalid workspace path: {}".format(
                            relative_path
                        )
                    )
                    continue

            except ValueError:
                errors.append(
                    "Invalid workspace path: {}".format(
                        relative_path
                    )
                )
                continue

            if not os.path.isfile(file_path):
                errors.append(
                    "File does not exist: {}".format(
                        relative_path
                    )
                )
                continue

            if not file_path.lower().endswith(".fcstd"):
                errors.append(
                    "Not a FreeCAD document: {}".format(
                        relative_path
                    )
                )
                continue

            try:
                # Check whether the document is already open.
                existing_document = None

                for doc in FreeCAD.listDocuments().values():

                    doc_path = getattr(
                        doc,
                        "FileName",
                        ""
                    )

                    if not doc_path:
                        continue

                    if os.path.realpath(doc_path) == file_path:
                        existing_document = doc
                        break

                if existing_document is not None:

                    FreeCAD.Console.PrintMessage(
                        "PLM: Document already open: {}\n".format(
                            relative_path
                        )
                    )

                    last_document = existing_document

                    already_open_count += 1

                else:
                    # Open the document in FreeCAD.
                    FreeCAD.Console.PrintMessage(
                        "PLM: Opening workspace part: {}\n".format(
                            file_path
                        )
                    )

                    doc = FreeCAD.openDocument(
                        file_path
                    )

                    if doc is None:
                        raise RuntimeError(
                            "FreeCAD did not return a document."
                        )

                    last_document = doc

                    opened_count += 1

            except Exception as exc:

                errors.append(
                    "{}: {}".format(
                        relative_path,
                        exc
                    )
                )

                FreeCAD.Console.PrintError(
                    "PLM: Failed to open {}: {}\n".format(
                        relative_path,
                        exc
                    )
                )

        # Activate the last successfully opened document.
        if last_document is not None:

            try:
                FreeCAD.setActiveDocument(
                    last_document.Name
                )

                FreeCADGui.activeDocument().activeView().viewAxonometric()
                FreeCADGui.activeDocument().activeView().fitAll()

            except Exception as exc:
                FreeCAD.Console.PrintWarning(
                    "PLM: Could not update document view: {}\n".format(
                        exc
                    )
                )

        # Display results.
        summary = (
            "Opened {} document(s). "
            "{} already open.".format(
                opened_count,
                already_open_count
            )
        )

        if errors:
            summary += "\n\nErrors:\n" + "\n".join(errors)

            QtWidgets.QMessageBox.warning(
                self.dialog,
                "Open in FreeCAD",
                summary
            )

        self.status_label.setText(
            summary
        )

        FreeCAD.Console.PrintMessage(
            "PLM: {}\n".format(
                summary.replace("\n", " ")
            )
        )

    # ---------------------------------------------------------
    # Import files into workspace
    # ---------------------------------------------------------

    def import_to_workspace(self):
        """Copy multiple FreeCAD documents into the workspace."""

        workspace = self.current_workspace

        if not workspace or not os.path.isdir(workspace):
            self.show_error(
                "Please select a valid workspace first."
            )
            return

        # Allow selecting multiple FreeCAD documents.
        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self.dialog,
            "Import FreeCAD Documents",
            os.path.expanduser("~"),
            "FreeCAD Documents (*.FCStd *.fcstd)"
        )

        if not file_paths:
            return

        # Check which selected files already exist in the workspace.
        conflicts = []

        for source_path in file_paths:
            destination_path = os.path.join(
                workspace,
                os.path.basename(source_path)
            )

            if os.path.exists(destination_path):
                conflicts.append(
                    os.path.basename(destination_path)
                )

        overwrite = False

        if conflicts:
            message = (
                "The following files already exist in the workspace:\n\n"
                + "\n".join(conflicts)
                + "\n\nOverwrite these files?"
            )

            answer = QtWidgets.QMessageBox.question(
                self.dialog,
                "Confirm Overwrite",
                message,
                QtWidgets.QMessageBox.Yes
                | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )

            if answer != QtWidgets.QMessageBox.Yes:
                return

            overwrite = True

        imported_count = 0
        skipped_count = 0
        errors = []

        for source_path in file_paths:
            try:
                source_path = os.path.abspath(source_path)
                filename = os.path.basename(source_path)

                destination_path = os.path.abspath(
                    os.path.join(workspace, filename)
                )

                # Avoid copying a file onto itself.
                if source_path == destination_path:
                    skipped_count += 1
                    continue

                if os.path.exists(destination_path) and not overwrite:
                    skipped_count += 1
                    continue

                # Copy the selected FreeCAD document.
                shutil.copy2(
                    source_path,
                    destination_path
                )

                imported_count += 1

                FreeCAD.Console.PrintMessage(
                    "PLM: Imported {} into workspace.\n".format(
                        destination_path
                    )
                )

            except Exception as exc:
                errors.append(
                    "{}: {}".format(
                        os.path.basename(source_path),
                        exc
                    )
                )

        # Refresh the local and server inventory.
        self.refresh_parts()

        # Report the outcome.
        summary = (
            "Import complete.\n\n"
            "Imported: {}\n"
            "Skipped: {}".format(
                imported_count,
                skipped_count
            )
        )

        if errors:
            summary += "\n\nErrors:\n" + "\n".join(errors)

        if errors:
            QtWidgets.QMessageBox.warning(
                self.dialog,
                "Import to Workspace",
                summary
            )
        else:
            self.status_label.setText(
                "Import complete: {} file(s) imported, {} skipped.".format(
                    imported_count,
                    skipped_count
                )
            )

            FreeCAD.Console.PrintMessage(
                "PLM: {}\n".format(
                    summary.replace("\n", " ")
                )
            )

    # ---------------------------------------------------------
    # Delete Workspace
    # ---------------------------------------------------------

    def delete_workspace(self):
        """Delete the selected workspace and remove it from saved settings."""

        workspace_path = self.workspace_combo.currentData()

        if not workspace_path:
            self.show_error(
                "Please select a workspace to delete."
            )
            return

        workspace_path = os.path.realpath(
            os.path.abspath(
                os.path.expanduser(str(workspace_path))
            )
        )

        if not os.path.isdir(workspace_path):
            self.show_error(
                "The workspace directory does not exist:\n{}".format(
                    workspace_path
                )
            )
            return

        # Prevent deletion if a FreeCAD document is open from this workspace.
        for doc in FreeCAD.listDocuments().values():
            doc_path = getattr(doc, "FileName", "")

            if not doc_path:
                continue

            doc_path = os.path.realpath(doc_path)

            try:
                inside_workspace = (
                    os.path.commonpath(
                        [workspace_path, doc_path]
                    ) == workspace_path
                )
            except ValueError:
                inside_workspace = False

            if inside_workspace:
                self.show_error(
                    "Cannot delete this workspace because a FreeCAD "
                    "document from it is open:\n\n"
                    "{}\n\n"
                    "Close the document and try again.".format(
                        doc_path
                    )
                )
                return

        # Confirm permanent deletion.
        answer = QtWidgets.QMessageBox.warning(
            self.dialog,
            "Delete Workspace",
            "Are you sure you want to permanently delete this workspace?\n\n"
            "{}\n\n"
            "All files and subdirectories inside this workspace "
            "will be deleted. This operation cannot be undone."
            .format(workspace_path),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if answer != QtWidgets.QMessageBox.Yes:
            return

        try:
            # Delete the directory and all its contents.
            shutil.rmtree(workspace_path)

        except Exception as exc:
            self.show_error(
                "Could not delete workspace:\n\n{}".format(exc)
            )
            return

        # Remove the workspace from the saved list.
        self.workspaces = [
            path for path in self.workspaces
            if os.path.realpath(os.path.abspath(path))
            != workspace_path
        ]

        self.save_workspaces()

        # Update the workspace dropdown without triggering multiple refreshes.
        self.workspace_combo.blockSignals(True)
        self.workspace_combo.clear()

        for path in self.workspaces:
            self.workspace_combo.addItem(
                os.path.basename(path) or path,
                path
            )

        if self.workspace_combo.count() > 0:
            self.workspace_combo.setCurrentIndex(0)

            new_workspace = str(
                self.workspace_combo.currentData()
            )

            self.settings.setValue(
                "workspace",
                new_workspace
            )
        else:
            new_workspace = ""

            self.settings.remove("workspace")

        self.settings.sync()
        self.workspace_combo.blockSignals(False)

        # Update the active workspace selection and table.
        self.current_workspace = new_workspace

        if new_workspace and os.path.isdir(new_workspace):
            self.workspace_path_label.setText(
                "Workspace directory: {}".format(new_workspace)
            )
        else:
            self.workspace_path_label.setText(
                "Workspace directory: Not selected"
            )

        self.refresh_parts()

        QtWidgets.QMessageBox.information(
            self.dialog,
            "Delete Workspace",
            "Workspace deleted successfully:\n\n{}".format(
                workspace_path
            )
        )

        FreeCAD.Console.PrintMessage(
            "PLM: Deleted workspace: {}\n".format(workspace_path)
        )
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
        """Handle workspace selection and automatically refresh its parts."""

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

        # Automatically refresh the parts table for the selected workspace.
        self.refresh_parts()
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

    def sync_with_server(self):
        """Download newer server versions of parts in the active workspace."""

        from PySide import QtWidgets

        workspace = getattr(self, "current_workspace", None)

        if not workspace or not os.path.isdir(workspace):
            QtWidgets.QMessageBox.warning(
                self.dialog,
                "Sync with Server",
                "Please select a valid workspace first."
            )
            return

        if not self.connection or not getattr(
                self.connection, "connected", False
        ):
            QtWidgets.QMessageBox.warning(
                self.dialog,
                "Sync with Server",
                "Please connect to the PLM server first."
            )
            return

        workspace = os.path.abspath(workspace)

        # Discover the local FreeCAD documents.
        local_parts = self.find_local_parts()

        if not local_parts:
            QtWidgets.QMessageBox.information(
                self.dialog,
                "Sync with Server",
                "No FreeCAD parts were found in the workspace."
            )
            return

        # Obtain local and server metadata.
        try:
            local_inventory = self.get_local_inventory()
            server_inventory = self.get_server_inventory(local_parts)

        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self.dialog,
                "Sync with Server",
                "Could not retrieve workspace or server inventory:\n\n{}".format(
                    exc
                )
            )
            return

        # Find parts whose server version is newer.
        updates = []

        for local_part in local_parts:
            # Support the relative-path representation used by the inventory.
            if isinstance(local_part, dict):
                relative_path = (
                        local_part.get("relativePath")
                        or local_part.get("file")
                        or local_part.get("path")
                        or local_part.get("name")
                )
            else:
                relative_path = str(local_part)

            if not relative_path:
                continue

            relative_path = str(relative_path).replace("\\", "/")

            local_path = os.path.abspath(
                os.path.join(workspace, relative_path)
            )

            # Prevent paths outside the selected workspace.
            if os.path.commonpath(
                    [workspace, local_path]
            ) != workspace:
                continue

            if not os.path.isfile(local_path):
                continue

            # Normalize paths to match the inventory dictionary keys.
            normalized_path = relative_path.replace("\\", "/").lower()
            filename_key = os.path.basename(normalized_path)

            # Resolve local inventory metadata.
            local_entry = (
                local_inventory.get(normalized_path)
                or local_inventory.get(filename_key)
                or {}
            )

            # Resolve server inventory metadata.
            server_entry = (
                server_inventory.get(normalized_path)
                or server_inventory.get(filename_key)
                or {}
            )

            local_version = local_entry.get("version")
            server_version = server_entry.get("version")
            if not server_entry.get("exists", False):
                continue

            # If the local version is unknown, offer to sync when
            # the server has a valid version.
            if local_version in (None, "", "Unknown", "—"):
                if server_version in (
                    None, "", "Unknown", "—", "Not in PLM"
                ):
                    continue

            elif not self.server_version_is_newer(
                local_version,
                server_version
            ):
                continue

            part_id = server_entry.get("plmPartId")

            if part_id is None:
                continue

            # Use the server record as the download metadata.
            server_part_data = dict(
                server_entry.get("part") or {}
            )

            # Preserve both values: PlmDownload may still use latestVersion.
            server_part_data["latestVersion"] = server_entry.get("legacyVersion")
            server_part_data["version"] = server_entry.get("version")

            updates.append({
                "path": local_path,
                "relative_path": relative_path,
                "part_id": part_id,
                "local_version": local_version,
                "server_version": server_version,
                "part_data": server_part_data,
            })

        if not updates:
            QtWidgets.QMessageBox.information(
                self.dialog,
                "Sync with Server",
                "All workspace parts are up to date."
            )
            return

        # Confirm the changes before replacing files.
        details = "\n".join(
            "{}: {} → {}".format(
                item["relative_path"],
                item["local_version"] or "Unknown",
                item["server_version"] or "Unknown",
            )
            for item in updates
        )

        answer = QtWidgets.QMessageBox.question(
            self.dialog,
            "Sync with Server",
            "The following parts have newer server versions:\n\n"
            "{}\n\nDownload and replace these local files?".format(details),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )

        if answer != QtWidgets.QMessageBox.Yes:
            return

        downloaded = 0
        skipped = 0
        failed = 0
        messages = []

        # Disable the button while synchronization is running.
        self.sync_button.setEnabled(False)

        try:
            for item in updates:
                path = item["path"]

                # Skip the main document if it is open and modified.
                modified_open_document = False

                for doc in FreeCAD.listDocuments().values():
                    doc_path = getattr(doc, "FileName", "")

                    if not doc_path:
                        continue

                    if (
                            os.path.normcase(os.path.realpath(doc_path))
                            == os.path.normcase(os.path.realpath(path))
                            and getattr(doc, "Modified", False)
                    ):
                        modified_open_document = True
                        break

                if modified_open_document:
                    skipped += 1
                    messages.append(
                        "Skipped {}: open with unsaved changes.".format(
                            item["relative_path"]
                        )
                    )
                    continue

                try:
                    result = PlmDownload.download_part(
                        connection=self.connection,
                        part_id=item["part_id"],
                        part_data=item["part_data"],
                        workspace=workspace,
                        force=True,
                        destination_path=path,
                    )

                    if result and os.path.isfile(result):
                        downloaded += 1
                    else:
                        failed += 1
                        messages.append(
                            "Failed to update {}.".format(
                                item["relative_path"]
                            )
                        )

                except Exception as exc:
                    failed += 1
                    messages.append(
                        "Failed to update {}: {}".format(
                            item["relative_path"],
                            exc
                        )
                    )

        finally:
            self.sync_button.setEnabled(True)

        # Refresh the table to display the latest inventory and versions.
        self.refresh_parts()

        summary = (
            "Synchronization finished.\n\n"
            "Updated: {}\n"
            "Skipped: {}\n"
            "Failed: {}".format(downloaded, skipped, failed)
        )

        if messages:
            summary += "\n\nDetails:\n" + "\n".join(messages)

        if failed:
            QtWidgets.QMessageBox.warning(
                self.dialog,
                "Sync with Server",
                summary
            )
        else:
            QtWidgets.QMessageBox.information(
                self.dialog,
                "Sync with Server",
                summary
            )
    # ---------------------------------------------------------
    # Remove parts from workspace
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # Remove parts from workspace
    # ---------------------------------------------------------

    def remove_from_workspace(self):
        """Remove selected local FreeCAD documents from the workspace.

        Deletes local files and removes their corresponding entries
        from workspace.json. Does not delete parts from the PLM server.
        """

        workspace = self.current_workspace

        if not workspace or not os.path.isdir(workspace):
            self.show_error("Please select a valid workspace first.")
            return

        workspace_root = os.path.realpath(workspace)

        # Get selected row numbers.
        selected_rows = sorted({
            index.row()
            for index in self.parts_table.selectionModel().selectedRows()
        })

        if not selected_rows:
            self.show_error(
                "Please select one or more parts to remove."
            )
            return

        # Collect selected files and their relative paths.
        files_to_remove = []

        for row in selected_rows:
            item = self.parts_table.item(row, 0)

            if item is None:
                continue

            relative_path = item.text().replace("\\", "/")

            file_path = os.path.realpath(
                os.path.join(workspace_root, relative_path)
            )

            try:
                if os.path.commonpath(
                    [workspace_root, file_path]
                ) != workspace_root:
                    self.show_error(
                        "Invalid workspace file path:\n{}".format(
                            relative_path
                        )
                    )
                    return

            except ValueError:
                self.show_error(
                    "Invalid workspace file path:\n{}".format(
                        relative_path
                    )
                )
                return

            if not os.path.isfile(file_path):
                continue

            files_to_remove.append({
                "relative_path": relative_path,
                "file_path": file_path
            })

        if not files_to_remove:
            self.show_error(
                "None of the selected files exists in the workspace."
            )
            self.refresh_parts()
            return

        # Confirm before deleting files.
        filenames = [
            entry["relative_path"]
            for entry in files_to_remove
        ]

        answer = QtWidgets.QMessageBox.question(
            self.dialog,
            "Remove from Workspace",
            "Remove the following {} file(s) from the workspace?\n\n"
            "{}\n\n"
            "The local files and their workspace inventory entries "
            "will be removed. The PLM server will not be modified."
            .format(
                len(files_to_remove),
                "\n".join(filenames)
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if answer != QtWidgets.QMessageBox.Yes:
            return

        removed_count = 0
        inventory_count = 0
        errors = []

        # Read workspace.json before deleting anything.
        try:
            inventory = WorkspaceInventory.get_workspace_inventory(
                workspace
            )

            parts = inventory.get("parts", {})

            if not isinstance(parts, dict):
                raise ValueError(
                    "The 'parts' field in workspace.json is invalid."
                )

        except Exception as exc:
            self.show_error(
                "Could not read workspace.json:\n{}".format(exc)
            )
            return

        # Build a map from normalized relative paths to part IDs.
        path_to_part_id = {}

        for inventory_id, part_data in parts.items():
            if not isinstance(part_data, dict):
                continue

            inventory_file = str(
                part_data.get("file") or ""
            ).replace("\\", "/")

            if inventory_file:
                normalized_path = os.path.normcase(
                    os.path.normpath(inventory_file)
                )

                path_to_part_id[normalized_path] = inventory_id

        # Delete files and remove corresponding inventory entries.
        for entry in files_to_remove:
            relative_path = entry["relative_path"]
            file_path = entry["file_path"]

            normalized_path = os.path.normcase(
                os.path.normpath(relative_path)
            )

            part_id = path_to_part_id.get(normalized_path)

            try:
                os.remove(file_path)
                removed_count += 1

                if part_id is not None:
                    WorkspaceInventory.remove_workspace_part(
                        workspace,
                        part_id
                    )

                    inventory_count += 1

                    # Avoid attempting to remove the same entry twice.
                    path_to_part_id.pop(normalized_path, None)

                    FreeCAD.Console.PrintMessage(
                        "PLM: Removed part {} from workspace.json.\n"
                        .format(part_id)
                    )

                else:
                    FreeCAD.Console.PrintWarning(
                        "PLM: Deleted {}, but no matching part ID "
                        "was found in workspace.json.\n".format(
                            relative_path
                        )
                    )

            except Exception as exc:
                errors.append(
                    "{}: {}".format(relative_path, exc)
                )

        # Refresh the table.
        self.refresh_parts()

        summary = (
            "Removed {} local file(s).\n"
            "Removed {} inventory entr(y/ies) from workspace.json."
            .format(
                removed_count,
                inventory_count
            )
        )

        if errors:
            summary += "\n\nErrors:\n" + "\n".join(errors)

            QtWidgets.QMessageBox.warning(
                self.dialog,
                "Remove from Workspace",
                summary
            )
        else:
            self.status_label.setText(summary)

        FreeCAD.Console.PrintMessage(
            "PLM: {}\n".format(summary.replace("\n", " "))
        )
    # ---------------------------------------------------------
    # Local workspace inventory
    # ---------------------------------------------------------

    def get_local_inventory(self):
        """
        Read local PLM part versions using WorkspaceInventory.

        Returns a dictionary indexed by normalized relative path
        and filename.
        """

        if (
            not self.current_workspace
            or not os.path.isdir(self.current_workspace)
        ):
            return {}

        try:
            # WorkspaceInventory owns workspace.json access.
            workspace_data = WorkspaceInventory.get_workspace_inventory(
                self.current_workspace
            )

        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                "PLM: Could not read workspace inventory: {}\n".format(
                    exc
                )
            )
            return {}

        if not isinstance(workspace_data, dict):
            return {}

        parts = workspace_data.get("parts", {})
        inventory = {}

        if not isinstance(parts, dict):
            return inventory

        for part in parts.values():
            if not isinstance(part, dict):
                continue

            filename = str(
                part.get("file") or ""
            ).replace("\\", "/")

            if not filename:
                continue

            version = part.get("cadVersion") or part.get("version")
            if version is not None and "." not in str(version):
                version = None  # legacy computedVersion, not a CAD revision

            if version is None:
                version_text = "Unknown"
            else:
                version_text = str(version)

            entry = {
                "version": version_text,
                "partId": part.get("partId"),
                "name": part.get("name", ""),
            }

            # Index by normalized relative path.
            inventory[filename.lower()] = entry

            # Also index by filename for older inventory entries.
            basename = os.path.basename(filename).lower()
            inventory.setdefault(basename, entry)

        return inventory
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

            # CAD version is independent of the legacy computedVersion.
            cad_version = part.get("version")
            if cad_version in (None, ""):
                major = part.get("majorVersion")
                minor = part.get("minorVersion")
                if major is not None and minor is not None:
                    cad_version = "{}.{}".format(major, minor)

            entry = {
                "version": str(cad_version) if cad_version not in (None, "") else "—",
                "legacyVersion": part.get("latestVersion"),
                "exists": part.get("existsInPlm", False),
                "status": part.get("lifecycleState") or "Unknown",
                "checkedOutBy": part.get("checkedOutBy") or "",
                "canCheckIn": part.get("canCheckIn"),
                "canCheckOut": part.get("canCheckOut"),
                "plmPartId": part.get("plmPartId"),
                "tags": part.get("tags", []),
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



    def server_version_is_newer(self, local_version, server_version):
        """Return True if the server version is greater than the local version."""

        if local_version in (None, "", "Unknown", "—"):
            return False

        if server_version in (None, "", "Unknown", "—", "Not in PLM"):
            return False

        def parse(value):
            text = str(value).strip()
            if not text or not all(piece.isdigit() for piece in text.split(".")):
                return None
            return tuple(int(piece) for piece in text.split("."))

        local = parse(local_version)
        server = parse(server_version)
        if local is None or server is None:
            return False
        # Do not compare legacy integer revisions against major.minor CAD
        # versions. They are different versioning schemes.
        if len(local) != len(server):
            return False
        return server > local


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
        local_inventory = self.get_local_inventory()

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
            # Local version from workspace.json.
            normalized_path = (
                relative_path.replace("\\", "/").lower()
            )

            filename = os.path.basename(
                relative_path
            ).lower()

            local_part = local_inventory.get(normalized_path)

            if local_part is None:
                local_part = local_inventory.get(filename)

            if local_part is None:
                local_version_text = "—"
            else:
                local_version_text = local_part["version"]

            local_version_item = QtWidgets.QTableWidgetItem(
                local_version_text
            )

            self.parts_table.setItem(
                row,
                1,
                local_version_item
            )
            version_text = "Unknown"
            server_part = None

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
                    version_text = "Not in PLM"
                else:
                    version_text = server_part["version"]

            version_item = QtWidgets.QTableWidgetItem(
                version_text
            )

            # Flag the server version in red if it is newer
            # than the locally recorded version.
            if server_part is not None and local_part is not None:
                local_compare = local_part.get("version")
                server_compare = server_part.get("version")
                if self.server_version_is_newer(
                        local_compare, server_compare
                ):
                    version_item.setForeground(
                        QtGui.QBrush(QtGui.QColor("red"))
                    )
                    version_item.setToolTip(
                        "A newer version is available on the PLM server."
                    )

            self.parts_table.setItem(
                row,
                2,
                version_item
            )

            # Lifecycle state
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

            if status_text == "CHECKED_OUT":
                status_item.setForeground(QtGui.QBrush(QtGui.QColor(0, 110, 180)))
            elif status_text == "RELEASED":
                status_item.setForeground(QtGui.QBrush(QtGui.QColor(0, 125, 55)))

            self.parts_table.setItem(row, 3, status_item)

            owner_text = "—"
            if server_part is not None:
                owner_text = server_part.get("checkedOutBy") or "—"
            owner_item = QtWidgets.QTableWidgetItem(str(owner_text))
            if server_part is not None and server_part.get("canCheckIn") is False:
                owner_item.setToolTip("Server reports that this user cannot check in this part.")
            self.parts_table.setItem(row, 4, owner_item)
            # -----------------------------------------------------
            # PLM Tags
            # -----------------------------------------------------

            tags_text = "—"

            if server_part is not None:

                tags = server_part.get("tags", [])

                if isinstance(tags, list):

                    tag_names = []

                    for tag in tags:

                        if isinstance(tag, dict):
                            name = tag.get("name", "")

                        else:
                            name = str(tag)

                        if name:
                            tag_names.append(str(name))

                    if tag_names:
                        tags_text = ", ".join(tag_names)

                elif isinstance(tags, str):

                    if tags.strip():
                        tags_text = tags.strip()

            tags_item = QtWidgets.QTableWidgetItem(
                tags_text
            )

            tags_item.setToolTip(
                tags_text
            )

            self.parts_table.setItem(
                row,
                5,
                tags_item
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