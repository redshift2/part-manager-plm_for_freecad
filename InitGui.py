# FreeCAD init script of the Parts Manager PLM module

import os
import FreeCAD
import FreeCADGui as Gui

def set_default_workspace_directory():
    """Set FreeCAD's default directory to the saved PLM workspace."""

    from PySide import QtCore
    import os

    settings = QtCore.QSettings()
    settings.beginGroup("PartsManagerPLM")

    workspace = settings.value("workspace", "")

    settings.endGroup()

    if not workspace:
        FreeCAD.Console.PrintMessage(
            "PLM workspace has not been configured.\n"
        )
        return

    workspace = os.path.abspath(
        os.path.expanduser(str(workspace))
    )

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

class PMPLMWorkbench(Workbench):

    "Parts Manager PLM workbench"

    def __init__(self):
        self.__class__.Icon = (
            FreeCAD.getUserAppDataDir()
            + "Mod/part-manager-plm_for_freecad/icons/icon.png"
        )
        self.__class__.MenuText = "Parts Manager PLM"
        self.__class__.ToolTip = "Parts Manager Workbench"

    def Initialize(self):
        # Ensure FreeCAD can locate the workbench modules.
        module_dir = os.path.join(
            FreeCAD.getUserAppDataDir(),
            "Mod",
            "part-manager-plm_for_freecad"
        )

        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)

        # Import existing modules.
        import Login
        import BrowseSearch
        import Workspace
        import SearchParts
        import plmcheckin

        # Explicitly register the Check-In command.
        plmcheckin.register_command()

        # Existing toolbar and menu commands.
        self.commands = [
            "PMPLM_Login",
            "PMPLM_BrowseByTag",
            "PMPLM_Workspace",
            "PMPLM_SearchParts",
            "PMPLM_CheckIn",
        ]

        self.appendToolbar("Parts Manager PLM", self.commands)
        self.appendMenu("PLM", self.commands)

        FreeCAD.Console.PrintMessage(
            "Parts Manager PLM commands initialized.\n"
        )

    def Activated(self):
        return

    def Deactivated(self):
        return

    def ContextMenu(self, recipient):
        self.appendContextMenu(
            self.__class__.MenuText,
            self.commands
        )

    def GetClassName(self):
        return "Gui::PythonWorkbench"


set_default_workspace_directory()

Gui.addWorkbench(PMPLMWorkbench())