# -*- coding: utf-8 -*-
"""Authenticated JSON client for the optional Global Workspace Grails API."""
from urllib.parse import urljoin
import requests


class GlobalWorkspaceApiError(RuntimeError):
    pass


class GlobalWorkspaceApi:
    def __init__(self, connection):
        self.connection = connection

    def _get(self, endpoint):
        connection = self.connection
        if not connection or not getattr(connection, 'connected', False):
            raise GlobalWorkspaceApiError('Connect to the PLM server first.')
        base = str(getattr(connection, 'url', '') or '').strip()
        session = getattr(connection, 'session', None)
        if not base or session is None:
            raise GlobalWorkspaceApiError('PLM server URL or authenticated session is missing.')
        url = urljoin(base.rstrip('/') + '/', endpoint.lstrip('/'))
        try:
            response = session.get(url, headers={'Accept': 'application/json'}, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise GlobalWorkspaceApiError('Request to {} failed: {}'.format(endpoint, exc)) from exc
        if not isinstance(payload, dict):
            raise GlobalWorkspaceApiError('Unexpected response from {}'.format(endpoint))
        if payload.get('success') is False:
            raise GlobalWorkspaceApiError(str(payload.get('error', 'Request failed')))
        return payload

    def _post(self, endpoint, data=None):
        connection = self.connection
        if not connection or not getattr(connection, 'connected', False):
            raise GlobalWorkspaceApiError('Connect to the PLM server first.')
        base = str(getattr(connection, 'url', '') or '').strip()
        session = getattr(connection, 'session', None)
        if not base or session is None:
            raise GlobalWorkspaceApiError('PLM server URL or authenticated session is missing.')
        url = urljoin(base.rstrip('/') + '/', endpoint.lstrip('/'))
        try:
            response = session.post(url, json=data or {},
                                    headers={'Accept': 'application/json'}, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            detail = ''
            if 'response' in locals():
                try:
                    detail = response.json().get('error', '')
                except Exception:
                    detail = response.text[:300]
            raise GlobalWorkspaceApiError('{}: {}'.format(endpoint, detail or exc)) from exc
        if not isinstance(payload, dict):
            raise GlobalWorkspaceApiError('Unexpected response from {}'.format(endpoint))
        if payload.get('success') is False:
            raise GlobalWorkspaceApiError(str(payload.get('error', 'Request failed')))
        return payload

    def create(self, name, description=''):
        return self._post('workspaceApi/create', {'name': name, 'description': description})

    def duplicate(self, workspace_id, name):
        return self._post('workspaceApi/duplicate/{}'.format(int(workspace_id)), {'name': name})

    def delete(self, workspace_id):
        return self._post('workspaceApi/delete/{}'.format(int(workspace_id)))

    def add_part(self, workspace_id, part_id, revision):
        return self._post('workspaceApi/addPart/{}'.format(int(workspace_id)),
                          {'partId': int(part_id), 'inventoryRevision': int(revision)})

    def remove_part(self, workspace_id, part_id, revision):
        return self._post('workspaceApi/removePart/{}'.format(int(workspace_id)),
                          {'partId': int(part_id), 'inventoryRevision': int(revision)})

    def approve_version(self, workspace_id, part_id, revision):
        return self._post('workspaceApi/approveVersion/{}'.format(int(workspace_id)),
                          {'partId': int(part_id), 'inventoryRevision': int(revision)})

    def members(self, workspace_id):
        return self._get('workspaceApi/members/{}'.format(int(workspace_id))).get('members', [])

    def set_member(self, workspace_id, username, role):
        return self._post('workspaceApi/setMember/{}'.format(int(workspace_id)),
                          {'username': username, 'role': role})

    def remove_member(self, workspace_id, user_id):
        return self._post('workspaceApi/removeMember/{}'.format(int(workspace_id)),
                          {'userId': int(user_id)})

    def list_workspaces(self):
        payload = self._get('workspaceApi/list')
        workspaces = payload.get('workspaces', [])
        if not isinstance(workspaces, list):
            raise GlobalWorkspaceApiError('Invalid workspace list returned by server.')
        return workspaces

    def inventory(self, workspace_id):
        payload = self._get('workspaceApi/inventory/{}'.format(int(workspace_id)))
        inventory = payload.get('inventory')
        if not isinstance(inventory, dict) or not isinstance(inventory.get('parts', {}), dict):
            raise GlobalWorkspaceApiError('Invalid workspace inventory returned by server.')
        return payload

    def search_parts(self, query):
        """Existing PLM search endpoint returns a JSON array."""
        connection = self.connection
        if not connection or not getattr(connection, 'connected', False):
            raise GlobalWorkspaceApiError('Connect to the PLM server first.')
        url = urljoin(str(connection.url).rstrip('/') + '/', 'plmJson/searchParts')
        try:
            response = connection.session.get(url, params={'originalName': query},
                                              headers={'Accept': 'application/json'}, timeout=30)
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            raise GlobalWorkspaceApiError('PLM part search failed: {}'.format(exc)) from exc
        if not isinstance(result, list):
            raise GlobalWorkspaceApiError('Unexpected PLM search response (expected list).')
        return result