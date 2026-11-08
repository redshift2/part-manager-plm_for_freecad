# Parts Manager PLM — namespace / cookiecutter-layout migration

- Canonical code is in `freecad/parts_manager_plm/`.
- Root `InitGui.py` is kept as a FreeCAD 1.1 legacy workbench registration shim.
- Resources are under `freecad/parts_manager_plm/resources/`.
- `pm_plm.proto` and `pm_plm_pb2.py` have private file/package names. Wire field numbers, enum numbers and message structure remain unchanged; server protocol is compatible.
- Old `freecad_plm_pb2.py` has been removed.
- `pyproject.toml` and `commands`, `features`, `resources` folders follow the supplied cookiecutter layout.

## Install
Remove the previous `part-manager-plm_for_freecad` addon directory completely (avoid stale .pyc), then install this new directory under FreeCAD Mod. Restart FreeCAD. Do not merge old `parts_manager_plm` package into this version.

## Verification
Import Taack's `freecad_plm_pb2` and `freecad.parts_manager_plm.pm_plm_pb2` in the same FreeCAD Python process; there should be no descriptor pool conflict. Run actual upload/check-in against your PLM server to confirm integration.

## Notes
The template's modern `init_gui.py` entry point is provided as a layout placeholder; the tested FreeCAD workbench registration mechanism remains the legacy root `InitGui.py`. No full migration to a modern workbench entry point has been claimed.
