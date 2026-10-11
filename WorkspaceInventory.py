# WorkspaceInventory.py
#
# Standalone workspace inventory utilities for Parts Manager PLM.
#
# Public API:
#   save_workspace_part(workspace, part_id, part_data, destination_path)
#
#   save_workspace_inventory(connection, workspace, fcstd_paths)
#
#   get_workspace_inventory(workspace)
#
#   get_workspace_part(workspace, part_id)
#
#   remove_workspace_part(workspace, part_id)
#

import os
import json
import tempfile

import FreeCAD


WORKSPACE_INVENTORY_FILENAME = "workspace.json"


def _inventory_path(workspace):
    """Return the absolute path to workspace.json."""

    workspace = os.path.abspath(
        os.path.expanduser(str(workspace))
    )

    return os.path.join(
        workspace,
        WORKSPACE_INVENTORY_FILENAME
    )


def get_workspace_inventory(workspace):
    """
    Read workspace.json.

    Returns:
        dict: The complete inventory, or an empty inventory if
              the file does not exist or cannot be read.
    """

    if not workspace:
        return {"parts": {}}

    workspace_file = _inventory_path(workspace)

    if not os.path.isfile(workspace_file):
        return {"parts": {}}

    try:
        with open(workspace_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"parts": {}}

        parts = data.get("parts")

        if not isinstance(parts, dict):
            data["parts"] = {}

        return data

    except (json.JSONDecodeError, OSError) as exc:
        FreeCAD.Console.PrintWarning(
            "PLM: Could not read workspace inventory: {}\n".format(
                exc
            )
        )

        return {"parts": {}}


def _write_workspace_inventory(workspace, workspace_data):
    """
    Write workspace.json atomically.

    Existing inventory data is written to a temporary file first.
    The temporary file is then atomically moved into place.
    """

    if not workspace:
        raise ValueError("Workspace directory is required.")

    workspace = os.path.abspath(
        os.path.expanduser(str(workspace))
    )

    if not os.path.isdir(workspace):
        raise ValueError(
            "Workspace directory does not exist: {}".format(
                workspace
            )
        )

    workspace_file = _inventory_path(workspace)

    fd, temp_path = tempfile.mkstemp(
        prefix="workspace_",
        suffix=".json.tmp",
        dir=workspace,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                workspace_data,
                f,
                indent=4
            )
            f.write("\n")

        os.replace(
            temp_path,
            workspace_file
        )

    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def save_workspace_part(
    workspace,
    part_id,
    part_data,
    destination_path
):
    """
    Record a downloaded PLM part and its server version.

    Args:
        workspace: Workspace directory.
        part_id: PLM database ID.
        part_data: Metadata returned by the server.
        destination_path: Absolute path to the local file.
    """

    if not workspace:
        raise ValueError("Workspace directory is required.")

    workspace = os.path.abspath(
        os.path.expanduser(str(workspace))
    )

    destination_path = os.path.abspath(
        os.path.expanduser(str(destination_path))
    )

    if not os.path.isdir(workspace):
        raise ValueError(
            "Workspace directory does not exist: {}".format(
                workspace
            )
        )

    # Prevent recording files outside the workspace.
    if os.path.commonpath(
        [workspace, destination_path]
    ) != workspace:
        raise ValueError(
            "Part file is outside the workspace."
        )

    workspace_data = get_workspace_inventory(workspace)

    parts = workspace_data.setdefault("parts", {})

    key = str(part_id)

    existing = parts.get(key, {})

    if not isinstance(existing, dict):
        existing = {}

    # Retrieve the server version.
    version = None

    if isinstance(part_data, dict):
        for field in (
            "computedVersion",
            "latestVersion",
            "version"
        ):
            if part_data.get(field) is not None:
                version = part_data[field]
                break

    # Preserve the previous version if the server supplied none.
    if version is None:
        version = existing.get("version")

    # Determine the filename.
    part_name = os.path.basename(destination_path)

    if isinstance(part_data, dict):
        part_name = (
            part_data.get("originalName")
            or part_data.get("name")
            or part_data.get("label")
            or existing.get("name")
            or part_name
        )

    parts[key] = {
        "partId": part_id,
        "name": part_name,
        "version": version,
        "file": os.path.relpath(
            destination_path,
            workspace
        ).replace("\\", "/"),
    }

    _write_workspace_inventory(
        workspace,
        workspace_data
    )

    FreeCAD.Console.PrintMessage(
        "PLM: Saved part {} with version {} to workspace.json.\n".format(
            part_id,
            version
        )
    )


def save_workspace_inventory(
    connection,
    workspace,
    fcstd_paths
):
    """
    Update workspace.json with server metadata for extracted documents.

    The server endpoint is:
        POST /plmJson/workspaceParts

    Args:
        connection: Authenticated PLM connection.
        workspace: Workspace directory.
        fcstd_paths: Absolute paths of extracted FreeCAD documents.
    """

    if not connection or not getattr(
        connection, "connected", False
    ):
        FreeCAD.Console.PrintWarning(
            "PLM: Cannot update inventory: not connected.\n"
        )
        return

    server_url = getattr(
        connection, "url", ""
    ).rstrip("/")

    session = getattr(
        connection, "session", None
    )

    if not server_url or session is None:
        FreeCAD.Console.PrintWarning(
            "PLM: Cannot update inventory: invalid connection.\n"
        )
        return

    workspace = os.path.abspath(
        os.path.expanduser(str(workspace))
    )

    request_parts = []
    local_paths = {}

    for path in fcstd_paths:
        path = os.path.abspath(path)

        if not os.path.isfile(path):
            continue

        try:
            relative_path = os.path.relpath(
                path,
                workspace
            )
        except ValueError:
            continue

        # Ignore files outside the workspace.
        if (
            relative_path == os.pardir
            or relative_path.startswith(
                os.pardir + os.sep
            )
        ):
            continue

        relative_path = relative_path.replace(
            "\\", "/"
        )

        request_parts.append({
            "name": os.path.basename(relative_path),
            "relativePath": relative_path,
        })

        local_paths[relative_path] = path

    if not request_parts:
        return

    url = server_url + "/plmJson/workspaceParts"
    response = None

    try:
        FreeCAD.Console.PrintMessage(
            "PLM: Looking up metadata for {} FreeCAD documents.\n".format(
                len(request_parts)
            )
        )

        response = session.post(
            url,
            json={"parts": request_parts},
            timeout=60,
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            return

        server_parts = data.get("parts", [])

        if not isinstance(server_parts, list):
            return

        workspace_data = get_workspace_inventory(
            workspace
        )

        parts = workspace_data.setdefault(
            "parts", {}
        )

        updated_count = 0

        for item in server_parts:

            if not isinstance(item, dict):
                continue

            part_id = item.get("plmPartId")

            # The server did not find this file in PLM.
            if part_id is None:
                continue

            relative_path = item.get("relativePath")

            local_path = None

            # Prefer matching the complete relative path.
            if relative_path:
                normalized = str(
                    relative_path
                ).replace("\\", "/")

                local_path = local_paths.get(
                    normalized
                )

            # Fall back to the filename only when unique.
            if local_path is None:
                returned_name = item.get("name")

                if returned_name:
                    matches = [
                        path
                        for rel, path in local_paths.items()
                        if os.path.basename(rel)
                        == os.path.basename(
                            str(returned_name)
                        )
                    ]

                    if len(matches) == 1:
                        local_path = matches[0]

            if local_path is None:
                FreeCAD.Console.PrintWarning(
                    "PLM: Could not match inventory entry "
                    "for part {} to an extracted document.\n".format(
                        part_id
                    )
                )
                continue

            version = item.get("latestVersion")

            if version is None:
                version = item.get("computedVersion")

            if version is None:
                version = item.get("version")

            key = str(part_id)

            existing = parts.get(key, {})

            if not isinstance(existing, dict):
                existing = {}

            # Preserve the previous version if necessary.
            if version is None:
                version = existing.get("version")

            parts[key] = {
                "partId": part_id,
                "name": (
                    item.get("originalName")
                    or existing.get("name")
                    or os.path.basename(local_path)
                ),
                "version": version,
                "file": os.path.relpath(
                    local_path,
                    workspace
                ).replace("\\", "/"),
            }

            updated_count += 1

        _write_workspace_inventory(
            workspace,
            workspace_data
        )

        FreeCAD.Console.PrintMessage(
            "PLM: Updated metadata for {} PLM parts.\n".format(
                updated_count
            )
        )

    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            "PLM: Failed to update workspace inventory: {}\n".format(
                exc
            )
        )

    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def get_workspace_part(workspace, part_id):
    """
    Return the inventory entry for a PLM part ID.

    Returns:
        dict or None
    """

    inventory = get_workspace_inventory(workspace)

    return inventory.get(
        "parts", {}
    ).get(str(part_id))


def remove_workspace_part(workspace, part_id):
    """
    Remove a PLM part entry from workspace.json.

    Does not delete the actual FreeCAD file.
    """

    inventory = get_workspace_inventory(workspace)

    parts = inventory.get("parts", {})

    key = str(part_id)

    if key not in parts:
        return False

    del parts[key]

    _write_workspace_inventory(
        workspace,
        inventory
    )

    FreeCAD.Console.PrintMessage(
        "PLM: Removed part {} from workspace inventory.\n".format(
            part_id
        )
    )

    return True