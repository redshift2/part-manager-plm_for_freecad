# PlmDownload.py
#
# Standalone download utilities for Parts Manager PLM.
# Can be imported by BrowseSearch.py, Workspace.py,
# or other modules.

import os
import re
import zipfile
import tempfile
import shutil

import FreeCAD


def get_active_workspace():
    """
    Return the active workspace saved by Workspace.py.
    """

    from PySide import QtCore
    import os

    settings = QtCore.QSettings(
        QtCore.QSettings.IniFormat,
        QtCore.QSettings.UserScope,
        "PMPLM",
        "PartsManager"
    )

    workspace = settings.value("workspace", "")

    if not workspace:
        FreeCAD.Console.PrintWarning(
            "PLM: No workspace is configured in QSettings.\n"
        )
        return None

    workspace = os.path.abspath(
        os.path.expanduser(str(workspace))
    )

    if not os.path.isdir(workspace):
        FreeCAD.Console.PrintWarning(
            "PLM: Workspace directory does not exist: {}\n".format(
                workspace
            )
        )
        return None

    return workspace
def download_part(connection, part_id, part_data=None, workspace=None):
    """
    Download a PLM part and extract its FreeCAD document into the workspace.

    Returns:
        str: Path to the downloaded .FCStd file on success.
        None: If the download or extraction fails.
    """
    response = None
    temporary_directory = None
    temporary_output = None

    try:
        # Validate connection.
        if connection is None or not getattr(connection, "connected", False):
            raise RuntimeError("Not connected to the PLM server.")

        server_url = getattr(connection, "url", "").rstrip("/")
        session = getattr(connection, "session", None)

        if not server_url:
            raise RuntimeError("The PLM server URL is not configured.")

        if session is None:
            raise RuntimeError("The PLM connection has no HTTP session.")

        # Resolve destination workspace.
        if workspace is None:
            workspace = get_active_workspace()

        if not workspace:
            raise RuntimeError("No workspace is configured.")

        workspace = os.path.abspath(
            os.path.expanduser(str(workspace))
        )
        os.makedirs(workspace, exist_ok=True)

        # Determine the expected local filename.
        part_data = part_data or {}

        original_name = (
            part_data.get("originalName")
            or part_data.get("name")
            or part_data.get("label")
            or ""
        )

        original_name = os.path.basename(
            str(original_name).replace("\\", "/")
        )

        if original_name.lower().endswith(".fcstd"):
            expected_filename = original_name
        elif original_name:
            expected_filename = original_name + ".FCStd"
        else:
            expected_filename = "plm_part_{}.FCStd".format(part_id)

        destination_path = os.path.abspath(
            os.path.join(workspace, expected_filename)
        )

        # Ensure the destination is inside the workspace.
        if os.path.commonpath([workspace, destination_path]) != workspace:
            raise RuntimeError("Invalid part filename.")

        # Avoid downloading an existing file.
        if os.path.isfile(destination_path):
            FreeCAD.Console.PrintMessage(
                "PLM: Part already exists in workspace: {}\n".format(
                    destination_path
                )
            )
            return destination_path

        # Download the ZIP archive.
        download_url = server_url + "/plm/downloadBinPart"

        FreeCAD.Console.PrintMessage(
            "PLM: Downloading part {}...\n".format(part_id)
        )

        response = session.get(
            download_url,
            params={"id": part_id},
            timeout=120,
            stream=True,
        )
        response.raise_for_status()

        # Store the archive in a temporary directory.
        temporary_directory = tempfile.mkdtemp(
            prefix="pmplm_download_"
        )
        zip_path = os.path.join(
            temporary_directory,
            "part.zip"
        )

        with open(zip_path, "wb") as output:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if chunk:
                    output.write(chunk)

        # Find the FreeCAD document in the ZIP.
        # ---------------------------------------------------------
        # Extract the complete archive, including linked parts.
        # ---------------------------------------------------------
        main_document_path = None
        extracted_count = 0

        with zipfile.ZipFile(zip_path, "r") as archive:
            archive_entries = archive.infolist()

            fcstd_files = []

            FreeCAD.Console.PrintMessage(
                "PLM: Archive contains {} entries:\n".format(
                    len(archive_entries)
                )
            )

            # Identify all FreeCAD documents and log the archive.
            for entry in archive_entries:
                name = entry.filename

                FreeCAD.Console.PrintMessage(
                    "  {}\n".format(name)
                )

                if entry.is_dir():
                    continue

                normalized_name = name.replace("\\", "/").lstrip("/")
                path_parts = normalized_name.split("/")

                # Reject unsafe paths.
                if (
                        not normalized_name
                        or ".." in path_parts
                        or os.path.isabs(normalized_name)
                ):
                    FreeCAD.Console.PrintWarning(
                        "PLM: Skipping unsafe archive entry: {}\n".format(
                            name
                        )
                    )
                    continue

                if normalized_name.lower().endswith(".fcstd"):
                    fcstd_files.append(
                        (name, normalized_name)
                    )

            if not fcstd_files:
                raise RuntimeError(
                    "The downloaded archive contains no .FCStd files."
                )

            FreeCAD.Console.PrintMessage(
                "PLM: Found {} FreeCAD documents in the archive.\n".format(
                    len(fcstd_files)
                )
            )

            # Determine which file is the main document.
            # Prefer the selected PLM part's original filename.
            expected_basename = os.path.basename(
                original_name
            ).lower() if original_name else ""

            main_entry = None

            if expected_basename:
                for archive_name, normalized_name in fcstd_files:
                    if (
                            os.path.basename(normalized_name).lower()
                            == expected_basename
                    ):
                        main_entry = (
                            archive_name,
                            normalized_name
                        )
                        break

            # Fallback: prefer the shallowest FreeCAD document.
            if main_entry is None:
                main_entry = sorted(
                    fcstd_files,
                    key=lambda item: (
                        item[1].count("/"),
                        len(item[1])
                    )
                )[0]

            # Extract every archive entry, preserving directory structure.
            for entry in archive_entries:
                archive_name = entry.filename
                normalized_name = archive_name.replace("\\", "/").lstrip("/")
                path_parts = normalized_name.split("/")

                if (
                        not normalized_name
                        or ".." in path_parts
                        or os.path.isabs(normalized_name)
                ):
                    continue

                output_path = os.path.abspath(
                    os.path.join(workspace, *path_parts)
                )

                # Ensure no archive entry escapes the workspace.
                if os.path.commonpath(
                        [workspace, output_path]
                ) != workspace:
                    raise RuntimeError(
                        "Archive entry escapes workspace: {}".format(
                            archive_name
                        )
                    )

                if entry.is_dir():
                    os.makedirs(output_path, exist_ok=True)
                    continue

                os.makedirs(
                    os.path.dirname(output_path),
                    exist_ok=True
                )

                # Write each file to a temporary file first.
                temporary_file = output_path + ".pmplm_tmp"

                try:
                    with archive.open(entry, "r") as source:
                        with open(temporary_file, "wb") as target:
                            shutil.copyfileobj(source, target)

                    os.replace(temporary_file, output_path)
                    extracted_count += 1

                finally:
                    if os.path.isfile(temporary_file):
                        try:
                            os.remove(temporary_file)
                        except OSError:
                            pass

                FreeCAD.Console.PrintMessage(
                    "PLM: Extracted {}\n".format(output_path)
                )

            # Resolve the main document's extracted path.
            main_archive_name, main_normalized_name = main_entry

            main_document_path = os.path.abspath(
                os.path.join(
                    workspace,
                    *main_normalized_name.split("/")
                )
            )

        if not os.path.isfile(main_document_path):
            raise RuntimeError(
                "Main FreeCAD document was not extracted: {}".format(
                    main_document_path
                )
            )

        FreeCAD.Console.PrintMessage(
            "PLM: Extracted {} files.\n".format(extracted_count)
        )

        destination_path = main_document_path

        FreeCAD.Console.PrintMessage(
            "PLM: Main document: {}\n".format(destination_path)
        )

        FreeCAD.Console.PrintMessage(
            "PLM: Download complete: {}\n".format(
                destination_path
            )
        )

        return destination_path

    except Exception as exc:
        FreeCAD.Console.PrintError(
            "PLM download failed for part {}: {}\n".format(
                part_id,
                exc
            )
        )

        # Remove an incomplete temporary output file.
        if temporary_output and os.path.isfile(temporary_output):
            try:
                os.remove(temporary_output)
            except OSError:
                pass

        return None

    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

        if temporary_directory and os.path.isdir(temporary_directory):
            shutil.rmtree(
                temporary_directory,
                ignore_errors=True
            )