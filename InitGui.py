# FreeCAD init script of the Parts Manager PLM module

import os
import sys
import importlib
import importlib.util

import FreeCAD
import FreeCADGui as Gui


class PMPLMWorkbench(Workbench):
    """Parts Manager PLM workbench."""

    def __init__(self):

        self.module_dir = os.path.join(
            FreeCAD.getUserAppDataDir(),
            "Mod",
            "part-manager-plm_for_freecad"
        )

        self.icon_dir = os.path.join(self.module_dir, "icons")

        self.__class__.Icon = os.path.join(self.icon_dir, "icon.png")

        self.__class__.MenuText = "PLM - Parts Manager"
        self.__class__.ToolTip = ("Parts Manager PLM Workbench")

    def Initialize(self):
        # FreeCAD may execute InitGui.py with separate global namespaces.
        import sys
        import importlib.util

        # Load our private package directly, without changing sys.path.
        # This avoids collisions with Taack's top-level module names.
        package_name = "parts_manager_plm"
        package_dir = os.path.join(self.module_dir, package_name)
        package_init = os.path.join(package_dir, "__init__.py")
        if package_name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                package_name,
                package_init,
                submodule_search_locations=[package_dir],
            )
            if spec is None or spec.loader is None:
                raise ImportError("Cannot load Parts Manager PLM package: " + package_init)
            package = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = package
            try:
                spec.loader.exec_module(package)
            except Exception:
                sys.modules.pop(package_name, None)
                raise

        # Import the command modules.
        from parts_manager_plm import Login, BrowseSearch, Workspace, SearchParts, plmcheckin

        # Register the Check-In command.
        plmcheckin.register_command()

        # Toolbar and menu commands.
        self.commands = [
            "PMPLM_Login",
            "PMPLM_BrowseByTag",
            "PMPLM_Workspace",
            "PMPLM_SearchParts",
            "PMPLM_CheckIn",
        ]

        self.appendToolbar(
            "Parts Manager PLM",
            self.commands
        )

        self.appendMenu(
            "PLM",
            self.commands
        )

        FreeCAD.Console.PrintMessage(
            "Parts Manager PLM commands initialized.\n"
        )

    def _set_default_workspace_directory(self):
        """Apply the PLM workspace only when this workbench is activated."""
        import os
        import FreeCAD
        from PySide import QtCore

        settings = QtCore.QSettings("PMPLM", "PartsManager")
        workspace = settings.value("workspace", "")
        if not workspace:
            return

        workspace = os.path.abspath(os.path.expanduser(str(workspace)))
        if not os.path.isdir(workspace):
            FreeCAD.Console.PrintWarning(
                "PLM workspace does not exist: {}\n".format(workspace)
            )
            return

        params = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/General"
        )
        params.SetString("WorkingDir", workspace)
        params.SetString("FileOpenSavePath", workspace)
        FreeCAD.Console.PrintMessage(
            "PLM default directory set to: {}\n".format(workspace)
        )

    def Activated(self):
        self._set_default_workspace_directory()

    def Deactivated(self):
        pass

    def ContextMenu(self, recipient):
        self.appendContextMenu(
            self.__class__.MenuText,
            self.commands
        )

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(PMPLMWorkbench())