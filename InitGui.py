# FreeCAD init script of the Part manager PLM module

class PMPLMWorkbench (Workbench):

    "Part Manager workbench object"

    def __init__(self):
        self.__class__.Icon = FreeCAD.getUserAppDataDir() + "Mod/part-manager-plm_for_freecad/icons/icon.png"
        self.__class__.MenuText = "Parts Manager PLM"
        self.__class__.ToolTip = "Parts Manager Workbench"

    def Initialize(self):
        import Intranet  #, MyModuleB # import here all the needed files that create your FreeCAD commands
       # self.cmds = ["intranet.py"]
        #self.appendToolbar(self.__class__.MenuText, self.cmds)
        #self.appendMenu(self.__class__.MenuText, self.cmds)
        self.commands = ["PMPLM_Intranet"]

        self.appendToolbar("Parts Manager PLM", self.commands)
        self.appendMenu("PLM", self.commands)
        # self.appendMenu(["An existing Menu", "My submenu"], self.list) # appends a submenu to an existing menu

    def Activated(self):
        '''This function is executed when the workbench is activated'''
        return

    def Deactivated(self):
        '''This function is executed when the workbench is deactivated'''
        return

    def ContextMenu(self, recipient):
        '''This is executed whenever the user right-clicks on screen'''
        # 'recipient' will be either 'view' or 'tree'
        self.appendContextMenu(self.__class__.MenuText, self.list) # add commands to the context menu

    def GetClassName(self):
        return "Gui::PythonWorkbench"

Gui.addWorkbench(PMPLMWorkbench())
