# FreeCAD init script of the Parts Manager PLM module

class PMPLMWorkbench(Workbench):

    "Parts Manager PLM workbench"

    def __init__(self):
        self.__class__.Icon = (FreeCAD.getUserAppDataDir() + "Mod/part-manager-plm_for_freecad/icons/icon.png" )
        self.__class__.MenuText = "Parts Manager PLM"
        self.__class__.ToolTip = "Parts Manager Workbench"

    def Initialize(self):
        import Intranet
        import Login
        import BrowseSearch
        import Workspace
        import SearchParts

        self.commands = [
            "PMPLM_Intranet",
            "PMPLM_Login",
            "PMPLM_BrowseByTag",
            "PMPLM_Workspace",
            "PMPLM_SearchParts"
        ]

        self.appendToolbar("Parts Manager PLM", self.commands)
        self.appendMenu("PLM", self.commands)

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


Gui.addWorkbench(PMPLMWorkbench())