# BrowseSearch.py
#
# Browse PLM tags, download parts, open parts, and add parts
# to the active FreeCAD Assembly.
#
# Does not import Intranet.py.

import os
import requests

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets

import Login
import PlmDownload

ICON_DIR = os.path.join(
    FreeCAD.getUserAppDataDir(),
    "Mod",
    "part-manager-plm_for_freecad",
    "icons"
)

class BrowseByTagPanel:

    def __init__(self):
        self.connection = Login.get_connection()

        self.showing_parts = False
        self.selected_tag_id = None

        self.dialog = QtWidgets.QDialog()
        self.dialog.setWindowTitle("Parts Manager PLM - Browse by Tag")
        self.dialog.resize(450, 550)

        self.build_ui()
        self.connect_signals()
        self.update_connection_status()
        self.update_action_buttons()

    # --------------------------------------------------------
    # Build the interface
    # --------------------------------------------------------

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout(self.dialog)

        # Tag navigation buttons.
        navigation_layout = QtWidgets.QHBoxLayout()

        self.refresh_button = QtWidgets.QPushButton("Refresh Tags")
        self.back_button = QtWidgets.QPushButton("Back to Tags")

        navigation_layout.addWidget(self.refresh_button)
        navigation_layout.addWidget(self.back_button)

        layout.addLayout(navigation_layout)

        # Tag and part tree.
        self.browse_tree = QtWidgets.QTreeWidget()
        self.browse_tree.setHeaderLabel("Tags and Parts")

        layout.addWidget(self.browse_tree)

        # Part action buttons.
        action_layout = QtWidgets.QHBoxLayout()

        self.download_button = QtWidgets.QPushButton("Download")
        self.open_button = QtWidgets.QPushButton("Open")
        self.add_assembly_button = QtWidgets.QPushButton(
            "Add to Assembly"
        )

        action_layout.addWidget(self.download_button)
        action_layout.addWidget(self.open_button)
        action_layout.addWidget(self.add_assembly_button)

        layout.addLayout(action_layout)

        # Status message.
        self.message_label = QtWidgets.QLabel()
        self.message_label.setWordWrap(True)

        layout.addWidget(self.message_label)

        # Connection status.
        self.connection_status_label = QtWidgets.QLabel()
        layout.addWidget(self.connection_status_label)

        self.login_button = QtWidgets.QPushButton(
            "Connect to PLM Server"
        )

        layout.addWidget(self.login_button)

    # --------------------------------------------------------
    # Signals
    # --------------------------------------------------------

    def connect_signals(self):
        self.refresh_button.clicked.connect(self.browse_by_tag)
        self.back_button.clicked.connect(self.return_to_tags)

        self.browse_tree.itemClicked.connect(
            self.browse_tag_selected
        )

        self.browse_tree.itemSelectionChanged.connect(
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
            Login.show_login_dialog
        )

    # --------------------------------------------------------
    # Connection status
    # --------------------------------------------------------

    def update_connection_status(self):
        # Refresh the reference in case Login replaced the
        # shared connection object.
        self.connection = Login.get_connection()

        if self.connection and getattr(
            self.connection, "connected", False
        ):
            server_url = getattr(self.connection, "url", "")

            self.connection_status_label.setText(
                "Connected to: {}".format(server_url)
            )

            self.login_button.setText("Login Settings")

        else:
            self.connection_status_label.setText(
                "Not connected to the PLM server."
            )

            self.login_button.setText("Connect to PLM Server")

    def require_connection(self):
        self.update_connection_status()

        if self.connection and getattr(
            self.connection, "connected", False
        ):
            return True

        self.message_label.setText(
            "Please connect to the PLM server first."
        )

        return False

    # --------------------------------------------------------
    # Assembly detection
    # --------------------------------------------------------

    def get_active_assembly(self):
        """
        Return the active Assembly::AssemblyObject, or None.

        Only the active document is checked.
        """

        doc = FreeCAD.ActiveDocument

        if doc is None:
            return None

        for obj in doc.Objects:
            try:
                if obj.isDerivedFrom("Assembly::AssemblyObject"):
                    return obj
            except Exception:
                continue

        return None

    # --------------------------------------------------------
    # Update action buttons
    # --------------------------------------------------------

    def update_action_buttons(self):
        item = self.browse_tree.currentItem()

        is_part_selected = (
            self.showing_parts
            and item is not None
            and item.data(0, QtCore.Qt.UserRole) is not None
        )

        connected = (
            self.connection is not None
            and getattr(self.connection, "connected", False)
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
    # Get the selected part
    # --------------------------------------------------------

    def get_selected_part(self):
        """
        Return (part_id, part_data) for the selected part.

        Return (None, None) if no part is selected.
        """

        if not self.showing_parts:
            return None, None

        item = self.browse_tree.currentItem()

        if item is None:
            return None, None

        part_id = item.data(0, QtCore.Qt.UserRole)
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
    # Browse tags
    # --------------------------------------------------------

    def browse_by_tag(self):
        """Load tags and build the hierarchical tree."""

        self.showing_parts = False
        self.selected_tag_id = None

        self.browse_tree.clear()
        self.message_label.clear()

        self.update_action_buttons()

        if not self.require_connection():
            return

        try:
            url = (
                self.connection.url.rstrip("/")
                + "/plmJson/tags"
            )

            response = self.connection.session.get(
                url,
                timeout=15
            )

            response.raise_for_status()
            tags = response.json()

            if not isinstance(tags, list):
                raise ValueError(
                    "The server returned an invalid tag list."
                )

            # Index tags by ID and name.
            tag_items_by_id = {}
            tag_items_by_name = {}

            for tag in tags:
                if not isinstance(tag, dict):
                    continue

                tag_id = tag.get("id")
                tag_name = tag.get("name")

                if tag_id is None or tag_name is None:
                    continue

                tag_name = str(tag_name)

                item = QtWidgets.QTreeWidgetItem([tag_name])

                item.setData(
                    0,
                    QtCore.Qt.UserRole,
                    tag_id
                )

                tag_items_by_id[tag_id] = item

                # Parent is currently returned by the server
                # as a tag name.
                tag_items_by_name.setdefault(tag_name, item)

            # Build the hierarchy.
            attached_items = set()

            for tag in tags:
                if not isinstance(tag, dict):
                    continue

                tag_id = tag.get("id")
                item = tag_items_by_id.get(tag_id)

                if item is None:
                    continue

                parent_name = tag.get("parent")

                if parent_name is None or not str(
                    parent_name
                ).strip():
                    self.browse_tree.addTopLevelItem(item)
                    attached_items.add(tag_id)
                    continue

                parent_item = tag_items_by_name.get(
                    str(parent_name)
                )

                if parent_item is not None and parent_item is not item:
                    parent_item.addChild(item)
                    attached_items.add(tag_id)

            # Any tag not attached above is a top-level tag.
            # This also allows tags with missing parents to appear.
            for tag_id, item in tag_items_by_id.items():
                if tag_id not in attached_items:
                    if item.parent() is None:
                        self.browse_tree.addTopLevelItem(item)

            self.browse_tree.expandAll()

            self.message_label.setText(
                "{} tag(s) loaded.".format(
                    len(tag_items_by_id)
                )
            )

        except (
            requests.RequestException,
            ValueError
        ) as exc:
            self.message_label.setText(
                "Unable to load tags: {}".format(exc)
            )

            FreeCAD.Console.PrintWarning(
                "Unable to load PLM tags: {}\n".format(exc)
            )

        self.update_action_buttons()

    # --------------------------------------------------------
    # Select a tag and show its parts
    # --------------------------------------------------------

    def browse_tag_selected(self, item, column):
        """Load the parts associated with the selected tag."""

        # Don't treat a part selection as another tag selection.
        if self.showing_parts:
            return

        tag_id = item.data(0, QtCore.Qt.UserRole)

        if tag_id is None:
            return

        if not self.require_connection():
            return

        self.selected_tag_id = tag_id

        try:
            url = (
                self.connection.url.rstrip("/")
                + "/plmJson/partsByTag"
            )

            response = self.connection.session.get(
                url,
                params={"tagId": tag_id},
                timeout=15
            )

            response.raise_for_status()
            parts = response.json()

            if not isinstance(parts, list):
                raise ValueError(
                    "The server returned an invalid parts list."
                )

            self.browse_tree.clear()
            self.showing_parts = True

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

                part_item = QtWidgets.QTreeWidgetItem(
                    [str(part_name)]
                )

                # Store the part ID and complete part data.
                part_item.setData(
                    0,
                    QtCore.Qt.UserRole,
                    part_id
                )

                part_item.setData(
                    0,
                    QtCore.Qt.UserRole + 1,
                    part
                )

                self.browse_tree.addTopLevelItem(part_item)

            self.message_label.setText(
                "{} part(s) found.".format(
                    self.browse_tree.topLevelItemCount()
                )
            )

        except (
            requests.RequestException,
            ValueError
        ) as exc:
            self.message_label.setText(
                "Unable to load parts: {}".format(exc)
            )

            FreeCAD.Console.PrintWarning(
                "Unable to load parts for tag {}: {}\n".format(
                    tag_id,
                    exc
                )
            )

        self.update_action_buttons()

    # --------------------------------------------------------
    # Return to the tag hierarchy
    # --------------------------------------------------------

    def return_to_tags(self):
        self.browse_by_tag()

    # --------------------------------------------------------
    # Download the selected part
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

    # --------------------------------------------------------
    # Open the selected part
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

        # Reuse an already-open document if possible.
        normalized_path = os.path.normcase(
            os.path.abspath(path)
        )

        for doc in FreeCAD.listDocuments().values():
            document_path = getattr(doc, "FileName", "")

            if not document_path:
                continue

            if os.path.normcase(
                os.path.abspath(document_path)
            ) == normalized_path:
                FreeCAD.setActiveDocument(doc.Name)

                self.message_label.setText(
                    "Part is already open."
                )
                return

        try:
            FreeCAD.openDocument(path)

            self.message_label.setText(
                "Opened: {}".format(
                    os.path.basename(path)
                )
            )

        except Exception as exc:
            self.message_label.setText(
                "Unable to open part: {}".format(exc)
            )

            FreeCAD.Console.PrintError(
                "Unable to open PLM part: {}\n".format(exc)
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

        # Download the part using the standalone utility.
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

        try:
            # Reuse the part document if it is already open.
            normalized_path = os.path.normcase(
                os.path.abspath(path)
            )

            part_doc = None

            for doc in FreeCAD.listDocuments().values():
                document_path = getattr(doc, "FileName", "")

                if not document_path:
                    continue

                if os.path.normcase(
                    os.path.abspath(document_path)
                ) == normalized_path:
                    part_doc = doc
                    break

            if part_doc is None:
                part_doc = FreeCAD.openDocument(path)

            # Choose a suitable object to link into the assembly.
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

            # Restore the original assembly document.
            FreeCAD.setActiveDocument(original_doc.Name)

            # Reacquire the assembly object from the original document.
            assembly = original_doc.getObject(assembly_name)

            if assembly is None:
                raise RuntimeError(
                    "The original assembly could not be found."
                )

            # Create a link to the downloaded component.
            link_name = "PLM_" + part_object.Name
            link = original_doc.addObject(
                "App::Link",
                link_name
            )

            link.setLink(part_object)
            link.Label = part_object.Label

            assembly.addObject(link)

            original_doc.recompute()

            FreeCADGui.activeDocument().activeView().fitAll()

            self.message_label.setText(
                "Added '{}' to the assembly.".format(
                    part_object.Label
                )
            )

        except Exception as exc:
            self.message_label.setText(
                "Unable to add part to assembly: {}".format(exc)
            )

            FreeCAD.Console.PrintError(
                "PLM Add to Assembly failed: {}\n".format(exc)
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


# ------------------------------------------------------------
# Keep the dialog alive while open
# ------------------------------------------------------------

_browse_by_tag_panel = None


def show_browse_by_tag():
    global _browse_by_tag_panel

    if (
        _browse_by_tag_panel is not None
        and _browse_by_tag_panel.dialog.isVisible()
    ):
        _browse_by_tag_panel.show()
        return

    _browse_by_tag_panel = BrowseByTagPanel()
    _browse_by_tag_panel.show()


# ------------------------------------------------------------
# FreeCAD command
# ------------------------------------------------------------

class CommandPMPLMBrowseByTag:

    def GetResources(self):
        return {
            "Pixmap": os.path.join(
                ICON_DIR,
                "catalog.svg"
            ),
            "MenuText": "Browse Catalog",
            "ToolTip": "Browse the parts catalog on the PLM server"
        }
    def IsActive(self):
        return True

    def Activated(self):
        show_browse_by_tag()


FreeCADGui.addCommand("PMPLM_BrowseByTag",CommandPMPLMBrowseByTag())