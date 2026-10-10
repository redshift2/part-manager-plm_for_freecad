# SearchParts.py
#
# Search PLM parts by name, download parts, open parts,
# and add parts to the active FreeCAD Assembly.
#
# Uses the existing Login.py and PlmDownload.py modules.
# Does not import Intranet.py or BrowseSearch.py.

import os
import requests

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets

import Login
import PlmDownload


# ============================================================
# Search Parts Panel
# ============================================================

class SearchPartsPanel:

    def __init__(self):

        self.connection = Login.get_connection()

        self.dialog = QtWidgets.QDialog()

        self.dialog.setWindowTitle(
            "Parts Manager PLM - Search Parts"
        )

        self.dialog.resize(500, 550)

        self.build_ui()
        self.connect_signals()

        self.update_connection_status()
        self.update_action_buttons()

    # --------------------------------------------------------
    # Build the interface
    # --------------------------------------------------------

    def build_ui(self):

        layout = QtWidgets.QVBoxLayout(self.dialog)

        # ----------------------------------------------------
        # Search field
        # ----------------------------------------------------

        search_label = QtWidgets.QLabel(
            "Enter part name:"
        )

        layout.addWidget(search_label)

        search_layout = QtWidgets.QHBoxLayout()

        self.part_name_edit = QtWidgets.QLineEdit()

        self.part_name_edit.setPlaceholderText(
            "Enter part name..."
        )

        self.search_button = QtWidgets.QPushButton(
            "Search"
        )

        search_layout.addWidget(
            self.part_name_edit,
            1
        )

        search_layout.addWidget(
            self.search_button
        )

        layout.addLayout(search_layout)

        # ----------------------------------------------------
        # Search results
        # ----------------------------------------------------

        self.parts_tree = QtWidgets.QTreeWidget()

        self.parts_tree.setHeaderLabel(
            "Search Results"
        )

        self.parts_tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )

        layout.addWidget(
            self.parts_tree,
            1
        )

        # ----------------------------------------------------
        # Three action buttons at the bottom
        # ----------------------------------------------------

        action_layout = QtWidgets.QHBoxLayout()

        self.download_button = QtWidgets.QPushButton(
            "Download"
        )

        self.open_button = QtWidgets.QPushButton(
            "Open"
        )

        self.add_assembly_button = QtWidgets.QPushButton(
            "Add to Assembly"
        )

        action_layout.addWidget(
            self.download_button
        )

        action_layout.addWidget(
            self.open_button
        )

        action_layout.addWidget(
            self.add_assembly_button
        )

        layout.addLayout(
            action_layout
        )

        # ----------------------------------------------------
        # Status message
        # ----------------------------------------------------

        self.message_label = QtWidgets.QLabel()

        self.message_label.setWordWrap(True)

        layout.addWidget(
            self.message_label
        )

        # ----------------------------------------------------
        # Connection status
        # ----------------------------------------------------

        self.connection_status_label = QtWidgets.QLabel()

        layout.addWidget(
            self.connection_status_label
        )

        self.login_button = QtWidgets.QPushButton(
            "Connect to PLM Server"
        )

        layout.addWidget(
            self.login_button
        )

    # --------------------------------------------------------
    # Connect signals
    # --------------------------------------------------------

    def connect_signals(self):

        self.search_button.clicked.connect(
            self.search_parts
        )

        self.part_name_edit.returnPressed.connect(
            self.search_parts
        )

        self.parts_tree.itemSelectionChanged.connect(
            self.update_action_buttons
        )

        self.download_button.clicked.connect(
            self.download_selected_part
        )

        self.open_button.clicked.connect(
            self.open_selected_part
        )

        self.add_assembly_button.clicked.connect(
            self.add_selected_part_to_assembly
        )

        self.login_button.clicked.connect(
            self.open_login_dialog
        )

    # --------------------------------------------------------
    # Login dialog
    # --------------------------------------------------------

    def open_login_dialog(self):

        Login.show_login_dialog()

        # Refresh the connection after closing the login dialog.
        self.update_connection_status()
        self.update_action_buttons()

    # --------------------------------------------------------
    # Connection status
    # --------------------------------------------------------

    def update_connection_status(self):

        # Refresh the connection in case Login replaced it.
        self.connection = Login.get_connection()

        if (
            self.connection
            and getattr(
                self.connection,
                "connected",
                False
            )
        ):

            server_url = getattr(
                self.connection,
                "url",
                ""
            )

            self.connection_status_label.setText(
                "Connected to: {}".format(
                    server_url
                )
            )

            self.login_button.setText(
                "Login Settings"
            )

        else:

            self.connection_status_label.setText(
                "Not connected to the PLM server."
            )

            self.login_button.setText(
                "Connect to PLM Server"
            )

    # --------------------------------------------------------
    # Require a connection
    # --------------------------------------------------------

    def require_connection(self):

        self.update_connection_status()

        if (
            self.connection
            and getattr(
                self.connection,
                "connected",
                False
            )
        ):
            return True

        self.message_label.setText(
            "Please connect to the PLM server first."
        )

        return False

    # --------------------------------------------------------
    # Find the active FreeCAD assembly
    # --------------------------------------------------------

    def get_active_assembly(self):
        """
        Return the active document's Assembly::AssemblyObject.

        Only the active document is checked.
        """

        doc = FreeCAD.ActiveDocument

        if doc is None:
            return None

        for obj in doc.Objects:

            try:

                if obj.isDerivedFrom(
                    "Assembly::AssemblyObject"
                ):
                    return obj

            except Exception:
                continue

        return None

    # --------------------------------------------------------
    # Update action buttons
    # --------------------------------------------------------

    def update_action_buttons(self):

        item = self.parts_tree.currentItem()

        part_id = None

        if item is not None:

            part_id = item.data(
                0,
                QtCore.Qt.UserRole
            )

        is_part_selected = (
            part_id is not None
        )

        connected = (
            self.connection is not None
            and getattr(
                self.connection,
                "connected",
                False
            )
        )

        self.download_button.setEnabled(
            is_part_selected and connected
        )

        self.open_button.setEnabled(
            is_part_selected and connected
        )

        self.add_assembly_button.setEnabled(
            is_part_selected
            and connected
            and self.get_active_assembly() is not None
        )

    # --------------------------------------------------------
    # Get selected part
    # --------------------------------------------------------

    def get_selected_part(self):
        """
        Return (part_id, part_data).

        Return (None, None) when no part is selected.
        """

        item = self.parts_tree.currentItem()

        if item is None:
            return None, None

        part_id = item.data(
            0,
            QtCore.Qt.UserRole
        )

        part_data = item.data(
            0,
            QtCore.Qt.UserRole + 1
        )

        if part_id is None:
            return None, None

        if not isinstance(part_data, dict):
            part_data = {}

        return part_id, part_data

    # --------------------------------------------------------
    # Search parts by name
    # --------------------------------------------------------

    def search_parts(self):
        """
        Search the PLM server using:

            /plmJson/searchParts?originalName=<part name>

        The server response is expected to be a JSON list
        containing part dictionaries with an ID and name.
        """

        self.parts_tree.clear()
        self.message_label.clear()

        self.update_action_buttons()

        if not self.require_connection():
            return

        part_name = self.part_name_edit.text().strip()

        if not part_name:

            self.message_label.setText(
                "Please enter a part name to search for."
            )

            return

        try:

            url = (
                self.connection.url.rstrip("/")
                + "/plmJson/searchParts"
            )

            response = self.connection.session.get(
                url,
                params={
                    "originalName": part_name
                },
                timeout=30
            )

            response.raise_for_status()

            parts = response.json()

            if not isinstance(parts, list):

                raise ValueError(
                    "The server returned an invalid parts list."
                )

            # Populate the results.
            for part in parts:

                if not isinstance(part, dict):
                    continue

                part_id = part.get("id")

                if part_id is None:
                    continue

                part_name = (
                    part.get("originalName")
                    or part.get("name")
                    or part.get("label")
                    or str(part_id)
                )

                item = QtWidgets.QTreeWidgetItem(
                    [str(part_name)]
                )

                # Store the part ID.
                item.setData(
                    0,
                    QtCore.Qt.UserRole,
                    part_id
                )

                # Store the complete server response.
                # PlmDownload can use this metadata.
                item.setData(
                    0,
                    QtCore.Qt.UserRole + 1,
                    part
                )

                self.parts_tree.addTopLevelItem(
                    item
                )

            result_count = (
                self.parts_tree.topLevelItemCount()
            )

            self.message_label.setText(
                "{} part(s) found.".format(
                    result_count
                )
            )

            if result_count > 0:

                self.parts_tree.setCurrentItem(
                    self.parts_tree.topLevelItem(0)
                )

        except (
            requests.RequestException,
            ValueError
        ) as exc:

            self.message_label.setText(
                "Unable to search parts: {}".format(
                    exc
                )
            )

            FreeCAD.Console.PrintWarning(
                "PLM part search failed: {}\n".format(
                    exc
                )
            )

        except Exception as exc:

            self.message_label.setText(
                "Unexpected search error: {}".format(
                    exc
                )
            )

            FreeCAD.Console.PrintError(
                "Unexpected PLM search error: {}\n".format(
                    exc
                )
            )

        self.update_action_buttons()

    # --------------------------------------------------------
    # Download selected part
    # --------------------------------------------------------

    def download_selected_part(self):

        if not self.require_connection():
            return

        part_id, part_data = self.get_selected_part()

        if part_id is None:

            self.message_label.setText(
                "Please select a part."
            )

            return

        try:

            path = PlmDownload.download_part(
                connection=Login.get_connection(),
                part_id=part_id,
                part_data=part_data
            )

            if path:

                self.message_label.setText(
                    "Part downloaded: {}".format(
                        os.path.basename(path)
                    )
                )

            else:

                self.message_label.setText(
                    "Download failed. Check the FreeCAD console."
                )

        except Exception as exc:

            self.message_label.setText(
                "Unable to download part: {}".format(
                    exc
                )
            )

            FreeCAD.Console.PrintError(
                "PLM part download failed: {}\n".format(
                    exc
                )
            )

    # --------------------------------------------------------
    # Download and open selected part
    # --------------------------------------------------------

    def open_selected_part(self):

        if not self.require_connection():
            return

        part_id, part_data = self.get_selected_part()

        if part_id is None:

            self.message_label.setText(
                "Please select a part."
            )

            return

        try:

            path = PlmDownload.download_part(
                connection=Login.get_connection(),
                part_id=part_id,
                part_data=part_data
            )

            if not path:

                self.message_label.setText(
                    "Unable to download the selected part."
                )

                return

            # Normalize the path for comparison.
            normalized_path = os.path.normcase(
                os.path.abspath(path)
            )

            # Reuse an already-open document.
            for doc in FreeCAD.listDocuments().values():

                document_path = getattr(
                    doc,
                    "FileName",
                    ""
                )

                if not document_path:
                    continue

                if os.path.normcase(
                    os.path.abspath(document_path)
                ) == normalized_path:

                    FreeCAD.setActiveDocument(
                        doc.Name
                    )

                    self.message_label.setText(
                        "Part is already open: {}".format(
                            os.path.basename(path)
                        )
                    )

                    self.update_action_buttons()

                    return

            # Open the downloaded document.
            FreeCAD.openDocument(path)

            self.message_label.setText(
                "Opened: {}".format(
                    os.path.basename(path)
                )
            )

        except Exception as exc:

            self.message_label.setText(
                "Unable to open part: {}".format(
                    exc
                )
            )

            FreeCAD.Console.PrintError(
                "Unable to open PLM part: {}\n".format(
                    exc
                )
            )

        self.update_action_buttons()

    # --------------------------------------------------------
    # Add selected part to active Assembly
    # --------------------------------------------------------

    def add_selected_part_to_assembly(self):

        if not self.require_connection():
            return

        part_id, part_data = self.get_selected_part()

        if part_id is None:

            self.message_label.setText(
                "Please select a part."
            )

            return

        # The original document must contain the active assembly.
        original_doc = FreeCAD.ActiveDocument

        if original_doc is None:

            self.message_label.setText(
                "There is no active FreeCAD document."
            )

            return

        assembly = self.get_active_assembly()

        if assembly is None:

            self.message_label.setText(
                "Open a document containing an Assembly "
                "and make it active first."
            )

            return

        assembly_name = assembly.Name

        # ----------------------------------------------------
        # Download the part
        # ----------------------------------------------------

        try:

            path = PlmDownload.download_part(
                connection=Login.get_connection(),
                part_id=part_id,
                part_data=part_data
            )

            if not path:

                self.message_label.setText(
                    "Unable to download the selected part."
                )

                return

            # ------------------------------------------------
            # Reuse an already-open part document if possible
            # ------------------------------------------------

            normalized_path = os.path.normcase(
                os.path.abspath(path)
            )

            part_doc = None

            for doc in FreeCAD.listDocuments().values():

                document_path = getattr(
                    doc,
                    "FileName",
                    ""
                )

                if not document_path:
                    continue

                if os.path.normcase(
                    os.path.abspath(document_path)
                ) == normalized_path:

                    part_doc = doc
                    break

            if part_doc is None:

                part_doc = FreeCAD.openDocument(
                    path
                )

            # ------------------------------------------------
            # Find a suitable object to link
            # ------------------------------------------------

            part_object = None

            preferred_types = (
                "Assembly::AssemblyObject",
                "App::Part",
                "PartDesign::Body",
                "Part::Feature",
            )

            for type_id in preferred_types:

                for obj in part_doc.Objects:

                    try:

                        if obj.isDerivedFrom(type_id):

                            part_object = obj
                            break

                    except Exception:
                        continue

                if part_object is not None:
                    break

            if part_object is None:

                raise RuntimeError(
                    "No suitable part or assembly object "
                    "was found in the downloaded document."
                )

            part_object_name = part_object.Name
            part_object_label = part_object.Label

            # ------------------------------------------------
            # Restore the original assembly document
            # ------------------------------------------------

            FreeCAD.setActiveDocument(
                original_doc.Name
            )

            assembly = original_doc.getObject(
                assembly_name
            )

            if assembly is None:

                raise RuntimeError(
                    "The original assembly could not be found."
                )

            # ------------------------------------------------
            # Create a link in the assembly
            # ------------------------------------------------

            link = original_doc.addObject(
                "App::Link",
                "PLM_" + part_object_name
            )

            link.setLink(
                part_object
            )

            link.Label = part_object_label

            assembly.addObject(
                link
            )

            original_doc.recompute()

            # Refresh the FreeCAD view.
            try:

                FreeCADGui.activeDocument().activeView().fitAll()

            except Exception:
                pass

            self.message_label.setText(
                "Added '{}' to the assembly.".format(
                    part_object_label
                )
            )

        except Exception as exc:

            self.message_label.setText(
                "Unable to add part to assembly: {}".format(
                    exc
                )
            )

            FreeCAD.Console.PrintError(
                "PLM Add to Assembly failed: {}\n".format(
                    exc
                )
            )

        self.update_action_buttons()

    # --------------------------------------------------------
    # Show the dialog
    # --------------------------------------------------------

    def show(self):

        self.update_connection_status()
        self.update_action_buttons()

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()


# ============================================================
# Keep the dialog alive while open
# ============================================================

_search_parts_panel = None


def show_search_parts():

    global _search_parts_panel

    if (
        _search_parts_panel is not None
        and _search_parts_panel.dialog.isVisible()
    ):

        _search_parts_panel.show()
        return

    _search_parts_panel = SearchPartsPanel()

    _search_parts_panel.show()


# ============================================================
# FreeCAD command
# ============================================================

class CommandPMPLMSearchParts:

    def GetResources(self):

        return {
            "MenuText": "Search Parts",
            "ToolTip": "Search PLM parts by name",
        }

    def IsActive(self):

        return True

    def Activated(self):

        show_search_parts()


FreeCADGui.addCommand("PMPLM_SearchParts", CommandPMPLMSearchParts())