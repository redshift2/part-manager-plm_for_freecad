# -*- coding: utf-8 -*-
"""Global Workspace entry point for Parts Manager PLM.

The current server WorkspaceController exposes HTML pages, not a JSON
workspace API. This panel therefore links to the authenticated web UI
rather than scraping HTML or guessing API response formats.
"""
from urllib.parse import urljoin
from PySide import QtCore, QtGui, QtWidgets


class GlobalWorkspacePanel(QtWidgets.QWidget):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel('Global Workspaces')
        font = heading.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        heading.setFont(font)
        layout.addWidget(heading)
        description = QtWidgets.QLabel(
            'Global workspaces are stored on the PLM server and can be shared '
            'with other users. Manage them in the server workspace manager.')
        description.setWordWrap(True)
        layout.addWidget(description)
        button = QtWidgets.QPushButton('Open Global Workspace Manager in Browser')
        button.clicked.connect(self.open_manager)
        layout.addWidget(button)
        note = QtWidgets.QLabel(
            'Native workspace browsing and synchronization will require JSON '
            'endpoints on the server. Your existing local workspace is unchanged.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def open_manager(self):
        base = str(getattr(self.connection, 'url', '') or '').strip()
        if not base:
            QtWidgets.QMessageBox.warning(self, 'Global Workspaces',
                                          'No PLM server URL is configured.')
            return
        url = urljoin(base.rstrip('/') + '/', 'workspace/index')
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
