# plmupload.py
#
# Standalone FreeCAD PLM upload module.
#
# Dependencies:
#   login.py
#   freecad_plm_pb2.py
#
# Public API:
#   uploader = PlmUploader()
#   result = uploader.upload_documents()
#
#   uploader = PlmUploader(documents=[FreeCAD.ActiveDocument])
#   result = uploader.upload_documents()
#
# The authenticated HTTP session is shared through login.py.

import os
import json
import hashlib
import tempfile
import zipfile

from io import BytesIO

import FreeCAD
import requests

import freecad_plm_pb2 as PlmBuf

from Login import get_connection


class PlmUploadError(Exception):
    """Raised when a PLM upload fails."""


class PlmUploader:
    """Upload FreeCAD documents to the Parts Manager PLM server."""

    PROTO_UPLOAD_ENDPOINT = "plmProto/uploadProto"
    FILE_UPLOAD_ENDPOINT = "plmProto/uploadZip"
    RESET_ENDPOINT = "plmProto/reset"

    MAX_FILES_PER_ZIP = 16
    LARGE_UPLOAD_WARNING_MB = 500

    def __init__(self, connection=None, documents=None):
        """
        Args:
            connection:
                Shared connection from login.py.

            documents:
                Optional list of FreeCAD Document objects.
                If omitted, upload the active document and its
                modified linked documents.
        """

        self.connection = connection or get_connection()

        self.documents = documents

        self.sha_one_map = {}
        self.visited_documents = set()

    # ------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------

    def _require_connection(self):
        if not self.connection.connected:
            raise PlmUploadError(
                "Not connected to the PLM server."
            )

        if not self.connection.url:
            raise PlmUploadError(
                "The PLM server URL is not configured."
            )

    def _url(self, endpoint):
        return self.connection.url.rstrip("/") + "/" + endpoint

    # ------------------------------------------------------------
    # Document discovery
    # ------------------------------------------------------------

    def get_upload_documents(self):
        """
        Return documents to upload.

        If documents were explicitly supplied to the constructor,
        use exactly that list.

        Otherwise:
          - Include the active document.
          - Discover linked documents recursively.
          - Include linked documents modified since their last
            successful upload baseline.
        """

        if self.documents is not None:
            return self._unique_documents(self.documents)

        active_doc = FreeCAD.ActiveDocument

        if active_doc is None:
            return []

        documents = [active_doc]
        linked_documents = []

        visited_documents = {active_doc.Name}
        visited_objects = set()

        for obj in active_doc.Objects:
            self._scan_object_for_links(
                obj,
                linked_documents,
                visited_documents,
                visited_objects,
            )

        for linked_doc in linked_documents:
            if self._document_was_modified(
                linked_doc,
                active_doc,
            ):
                documents.append(linked_doc)

        return self._unique_documents(documents)

    @staticmethod
    def _unique_documents(documents):
        result = []
        seen = set()

        for doc in documents:
            if doc is None:
                continue

            name = getattr(doc, "Name", None)

            if not name or name in seen:
                continue

            seen.add(name)
            result.append(doc)

        return result

    @staticmethod
    def _is_link_object(obj):
        try:
            if obj.isDerivedFrom("App::Link"):
                return True
        except Exception:
            pass

        try:
            if obj.isDerivedFrom("Assembly::AssemblyLink"):
                return True
        except Exception:
            pass

        return False

    @staticmethod
    def _get_linked_document(obj):
        try:
            linked = getattr(obj, "LinkedObject", None)

            if linked is not None:
                return linked.Document
        except Exception:
            pass

        try:
            linked = obj.getLinkedObject()

            if linked is not None:
                return linked.Document
        except Exception:
            pass

        return None

    def _scan_object_for_links(
        self,
        obj,
        documents,
        visited_documents,
        visited_objects,
    ):
        if obj is None:
            return

        try:
            object_key = (
                obj.Document.Name,
                obj.Name,
            )
        except Exception:
            object_key = id(obj)

        if object_key in visited_objects:
            return

        visited_objects.add(object_key)

        if self._is_link_object(obj):
            linked_doc = self._get_linked_document(obj)

            if linked_doc is not None:
                doc_name = linked_doc.Name

                if doc_name not in visited_documents:
                    visited_documents.add(doc_name)
                    documents.append(linked_doc)

                    self._scan_document_for_links(
                        linked_doc,
                        documents,
                        visited_documents,
                        visited_objects,
                    )

            return

        children = []

        try:
            children.extend(obj.Group or [])
        except Exception:
            pass

        try:
            children.extend(obj.claimChildren() or [])
        except Exception:
            pass

        for child in children:
            self._scan_object_for_links(
                child,
                documents,
                visited_documents,
                visited_objects,
            )

    def _scan_document_for_links(
        self,
        doc,
        documents,
        visited_documents,
        visited_objects,
    ):
        for obj in getattr(doc, "Objects", []):
            self._scan_object_for_links(
                obj,
                documents,
                visited_documents,
                visited_objects,
            )

    # ------------------------------------------------------------
    # Modified document baseline
    # ------------------------------------------------------------

    @staticmethod
    def _get_modified_baseline():
        param = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/PartsManagerPLM"
        )

        raw = param.GetString(
            "ModifiedFileBaseline",
            "{}",
        )

        try:
            return json.loads(raw)
        except Exception:
            return {}

    @staticmethod
    def _save_modified_baseline(baseline):
        param = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/PartsManagerPLM"
        )

        param.SetString(
            "ModifiedFileBaseline",
            json.dumps(baseline),
        )

    @staticmethod
    def _get_file_mtime_ns(filename):
        try:
            return os.stat(filename).st_mtime_ns
        except (OSError, TypeError):
            return None

    def _get_assembly_baseline(self, assembly_doc):
        filename = getattr(assembly_doc, "FileName", "")

        if not filename:
            return {}

        baseline = self._get_modified_baseline()

        return baseline.get(
            os.path.abspath(filename),
            {},
        )

    def _document_was_modified(self, doc, assembly_doc):
        filename = getattr(doc, "FileName", "")

        if not filename or not os.path.isfile(filename):
            return False

        filename = os.path.abspath(filename)

        current_mtime = self._get_file_mtime_ns(filename)

        if current_mtime is None:
            return False

        baseline = self._get_assembly_baseline(assembly_doc)

        previous_mtime = baseline.get(filename)

        # A document without a baseline has never been uploaded
        # through this assembly.
        if previous_mtime is None:
            return True

        return current_mtime > int(previous_mtime)

    def _record_modified_baseline(self, assembly_doc, documents):
        assembly_file = getattr(assembly_doc, "FileName", "")

        if not assembly_file:
            return

        assembly_file = os.path.abspath(assembly_file)

        baseline = self._get_modified_baseline()

        assembly_baseline = baseline.setdefault(
            assembly_file,
            {},
        )

        for doc in documents:
            filename = getattr(doc, "FileName", "")

            if not filename:
                continue

            filename = os.path.abspath(filename)
            mtime = self._get_file_mtime_ns(filename)

            if mtime is not None:
                assembly_baseline[filename] = mtime

        self._save_modified_baseline(baseline)

    # ------------------------------------------------------------
    # File utilities
    # ------------------------------------------------------------

    @staticmethod
    def compute_file_sha1(filename):
        sha1 = hashlib.sha1()

        with open(filename, "rb") as stream:
            while True:
                data = stream.read(65536)

                if not data:
                    break

                sha1.update(data)

        return sha1.hexdigest()

    @staticmethod
    def create_thumbnail(filename):
        """
        Return the embedded FreeCAD thumbnail, if available.
        """

        try:
            with zipfile.ZipFile(filename, "r") as archive:
                names = archive.namelist()

                if "Document.xml" not in names:
                    return None

                thumbnail = "thumbnails/Thumbnail.png"

                if thumbnail not in names:
                    return None

                return archive.read(thumbnail)

        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                "Could not read FreeCAD thumbnail: {}\n".format(
                    exc
                )
            )

            return None

    @staticmethod
    def _document_filename(doc):
        filename = getattr(doc, "FileName", "")

        if not filename:
            raise PlmUploadError(
                "Document '{}' has not been saved.".format(
                    getattr(doc, "Label", getattr(doc, "Name", ""))
                )
            )

        filename = os.path.abspath(filename)

        if not os.path.isfile(filename):
            raise PlmUploadError(
                "The saved file for '{}' does not exist:\n{}".format(
                    getattr(doc, "Label", doc.Name),
                    filename,
                )
            )

        return filename

    # ------------------------------------------------------------
    # Protobuf creation
    # ------------------------------------------------------------

    def create_bucket_protobuf(self, documents):
        """
        Create a protobuf Bucket containing exactly the documents
        provided to this method.
        """

        self.sha_one_map = {}
        self.visited_documents = set()

        bucket = PlmBuf.Bucket()

        documents = self._unique_documents(documents)

        if not documents:
            raise PlmUploadError(
                "There are no documents selected for upload."
            )

        allowed_documents = {
            doc.Name
            for doc in documents
        }

        for doc in documents:
            self.create_doc_protobuf(
                doc,
                bucket,
                allowed_documents,
            )

        return bucket

    def create_doc_protobuf(
        self,
        doc,
        bucket,
        allowed_documents,
    ):
        if doc is None:
            return None

        if doc.Name not in allowed_documents:
            return None

        if doc.Name in self.visited_documents:
            return doc.Name

        self.visited_documents.add(doc.Name)

        filename = self._document_filename(doc)

        try:
            file_stat = os.stat(filename)

            plm_file = PlmBuf.PlmFile()

            plm_file.cTimeNs = file_stat.st_ctime_ns
            plm_file.uTimeNs = file_stat.st_mtime_ns

            plm_file.name = doc.Name

            plm_file.id = (
                doc.Id
                if getattr(doc, "Id", "")
                else doc.Uid
            )

            plm_file.label = doc.Label
            plm_file.comment = getattr(doc, "Comment", "")
            plm_file.fileName = filename
            plm_file.createdDate = getattr(doc, "CreationDate", "")
            plm_file.createdBy = getattr(doc, "CreatedBy", "")
            plm_file.sha1hex = self.compute_file_sha1(filename)
            plm_file.lastModifiedDate = getattr(
                doc,
                "LastModifiedDate",
                "",
            )
            plm_file.lastModifiedBy = getattr(
                doc,
                "LastModifiedBy",
                "",
            )

            for obj in getattr(doc, "Objects", []):
                if not self._is_link_object(obj):
                    continue

                link_name = self.create_link_protobuf(
                    obj,
                    bucket,
                    allowed_documents,
                )

                if link_name is not None:
                    plm_file.externalLink.append(link_name)

            thumbnail = self.create_thumbnail(filename)

            if thumbnail is not None:
                plm_file.filePreview = thumbnail

            bucket.plmFiles[plm_file.name].CopyFrom(plm_file)

            self.sha_one_map[plm_file.sha1hex] = filename

            return doc.Name

        except Exception as exc:
            raise PlmUploadError(
                "Unable to create protobuf for '{}': {}".format(
                    doc.Label,
                    exc,
                )
            )

    def create_link_protobuf(
        self,
        obj,
        bucket,
        allowed_documents,
    ):
        if getattr(obj, "TypeId", "") != "App::Link":
            return None

        linked_object = getattr(obj, "LinkedObject", None)

        if linked_object is None:
            return None

        linked_doc = getattr(linked_object, "Document", None)

        if linked_doc is None:
            return None

        if linked_doc.Name not in allowed_documents:
            return None

        plm_link = PlmBuf.PlmLink()

        plm_link.linkedObject = linked_object.Name
        plm_link.linkClaimChild = obj.LinkClaimChild

        copy_mode = getattr(obj, "LinkCopyOnChange", "Disabled")

        copy_modes = {
            "Disabled": PlmBuf.PlmLink.LinkCopyOnChangeEnum.Disabled,
            "Enabled": PlmBuf.PlmLink.LinkCopyOnChangeEnum.Enabled,
            "Owned": PlmBuf.PlmLink.LinkCopyOnChangeEnum.Owned,
        }

        if copy_mode in copy_modes:
            plm_link.linkCopyOnChange = copy_modes[copy_mode]

        plm_link.linkTransform = obj.LinkTransform

        linked_name = self.create_doc_protobuf(
            linked_doc,
            bucket,
            allowed_documents,
        )

        if linked_name is None:
            return None

        plm_link.plmFile = linked_name

        bucket.links[linked_doc.Name].CopyFrom(plm_link)

        return linked_doc.Name

    # ------------------------------------------------------------
    # Upload size
    # ------------------------------------------------------------

    def calculate_upload_size(self, documents=None):
        documents = documents or self.get_upload_documents()

        total_bytes = 0

        for doc in documents:
            filename = getattr(doc, "FileName", "")

            if not filename:
                continue

            try:
                total_bytes += os.path.getsize(filename)
            except OSError:
                pass

        return total_bytes

    def confirm_large_upload(self, documents, parent=None):
        """
        Return False when a large upload is declined.

        When no GUI parent is supplied, this method does not display
        a dialog; the caller can handle confirmation itself.
        """

        total_bytes = self.calculate_upload_size(documents)
        total_mb = total_bytes / (1024 * 1024)

        if total_mb <= self.LARGE_UPLOAD_WARNING_MB:
            return True

        if parent is None or not FreeCAD.GuiUp:
            return True

        from PySide import QtWidgets

        message = (
            "This upload contains approximately "
            "{:.2f} MB of FreeCAD files.\n\n"
            "Large uploads may require significant RAM.\n\n"
            "Do you want to continue?"
        ).format(total_mb)

        answer = QtWidgets.QMessageBox.warning(
            parent,
            "Large Upload",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )

        return answer == QtWidgets.QMessageBox.Yes

    # ------------------------------------------------------------
    # Server response
    # ------------------------------------------------------------

    @staticmethod
    def _parse_bucket_response(response):
        response.raise_for_status()

        bucket = PlmBuf.Bucket()

        try:
            bucket.ParseFromString(response.content)
        except Exception as exc:
            raise PlmUploadError(
                "The server returned an invalid protobuf response: "
                + str(exc)
            )

        return bucket

    # ------------------------------------------------------------
    # Main upload
    # ------------------------------------------------------------

    def upload_documents(
        self,
        documents=None,
        progress_callback=None,
        confirm_callback=None,
    ):
        """
        Upload documents to the PLM server.

        Args:
            documents:
                Optional list of FreeCAD Document objects.
                If omitted, uses the constructor's document list or
                discovers the active document and modified links.

            progress_callback:
                Optional callable receiving integer progress values.

            confirm_callback:
                Optional callable receiving (total_bytes, documents).
                Return False to cancel a large upload.

        Returns:
            True on success.

        Raises:
            PlmUploadError on failure.
        """

        self._require_connection()

        if documents is None:
            documents = self.get_upload_documents()
        else:
            documents = self._unique_documents(documents)

        if not documents:
            raise PlmUploadError(
                "No FreeCAD documents are selected for upload."
            )

        total_bytes = self.calculate_upload_size(documents)

        if confirm_callback is not None:
            if confirm_callback(total_bytes, documents) is False:
                return False

        if progress_callback:
            progress_callback(0)

        active_doc = FreeCAD.ActiveDocument

        bucket = self.create_bucket_protobuf(documents)

        data = {"ajax": "true"}

        with tempfile.TemporaryDirectory() as temp_dir:
            proto_zip = os.path.join(temp_dir, "proto.zip")

            with zipfile.ZipFile(proto_zip, "w") as archive:
                archive.writestr(
                    "proto.bin",
                    bucket.SerializeToString(),
                )

            if progress_callback:
                progress_callback(10)

            # Send protobuf metadata.
            with open(proto_zip, "rb") as proto_file:
                response = self.connection.session.post(
                    self._url(self.PROTO_UPLOAD_ENDPOINT),
                    files={"proto.bin": proto_file},
                    data=data,
                    timeout=300,
                )

            response_bucket = self._parse_bucket_response(response)

            if response_bucket.status != PlmBuf.ServerStatus.OK_PROTO:
                raise PlmUploadError(
                    "The PLM server rejected the upload metadata."
                )

            # Remove files already present on the server.
            for server_sha1 in response_bucket.serverSha1Files:
                self.sha_one_map.pop(server_sha1, None)

            remaining_files = list(self.sha_one_map.items())

            total_groups = (
                len(remaining_files) + self.MAX_FILES_PER_ZIP - 1
            ) // self.MAX_FILES_PER_ZIP

            for group_index in range(total_groups):
                group = remaining_files[
                    group_index * self.MAX_FILES_PER_ZIP:
                    (group_index + 1) * self.MAX_FILES_PER_ZIP
                ]

                zip_path = os.path.join(
                    temp_dir,
                    "files{}.zip".format(group_index),
                )

                with zipfile.ZipFile(zip_path, "w") as archive:
                    for sha1, filename in group:
                        archive.write(filename, arcname=sha1)

                with open(zip_path, "rb") as files_zip:
                    response = self.connection.session.post(
                        self._url(self.FILE_UPLOAD_ENDPOINT),
                        files={"proto.bin": files_zip},
                        data=data,
                        timeout=300,
                    )

                response_bucket = self._parse_bucket_response(response)

                if response_bucket.status != PlmBuf.ServerStatus.OK_FILES:
                    raise PlmUploadError(
                        "The PLM server rejected file ZIP {}.".format(
                            group_index + 1
                        )
                    )
                    FreeCAD.Console.PrintError(
                        "\n===== PLM UPLOAD REJECTION DEBUG =====\n"
                    )

                    FreeCAD.Console.PrintError(
                        f"HTTP status: {response.status_code}\n"
                    )

                    FreeCAD.Console.PrintError(
                        f"Response body: {response.text[:5000]}\n"
                    )

                    FreeCAD.Console.PrintError(
                        "======================================\n"
                    )

                if progress_callback:
                    progress_callback(
                        30 + int(
                            60 * (group_index + 1) /
                            max(total_groups, 1)
                        )
                    )

            # Reset the server's temporary upload state.
            response = self.connection.session.post(
                self._url(self.RESET_ENDPOINT),
                data=data,
                timeout=60,
            )

            response.raise_for_status()

        # Update baselines only after successful upload completion.
        if active_doc is not None:
            self._record_modified_baseline(
                active_doc,
                documents,
            )

        if progress_callback:
            progress_callback(100)

        FreeCAD.Console.PrintMessage(
            "PLM upload completed successfully. "
            "{} document(s) uploaded.\n".format(len(documents))
        )

        return True


# ------------------------------------------------------------
# Convenient module-level API
# ------------------------------------------------------------

def upload_documents(
    documents=None,
    progress_callback=None,
    confirm_callback=None,
):
    """
    Convenience function for use by other FreeCAD modules.

    Example:
        from plmupload import upload_documents
        upload_documents([FreeCAD.ActiveDocument])
    """

    uploader = PlmUploader(documents=documents)

    return uploader.upload_documents(
        documents=documents,
        progress_callback=progress_callback,
        confirm_callback=confirm_callback,
    )


def get_upload_documents():
    """Return the active document and modified linked documents."""

    return PlmUploader().get_upload_documents()