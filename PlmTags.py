# -*- coding: utf-8 -*-

"""
Parts Manager PLM - Tag management.
"""

import requests

import Login


TAGS_ENDPOINT = "/plmJson/tags"
SET_TAGS_ENDPOINT = "/plmJson/setPartTags"


def get_tags(connection=None):
    """Retrieve available PLM tags."""

    if connection is None:
        connection = Login.get_connection()

    if not connection or not connection.connected:
        raise RuntimeError("Not connected to PLM server.")

    url = (
        connection.url.rstrip("/")
        + TAGS_ENDPOINT
    )

    response = connection.session.get(
        url,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        return data.get("tags", [])

    if isinstance(data, list):
        return data

    raise RuntimeError("Unexpected tags response.")


def set_part_tags(part_id, tag_ids, connection=None):
    """
    Replace the tags assigned to a PLM part.

    part_id: PLM part ID
    tag_ids: List of tag IDs
    """

    if connection is None:
        connection = Login.get_connection()

    if not connection or not connection.connected:
        raise RuntimeError("Not connected to PLM server.")

    url = (
        connection.url.rstrip("/")
        + SET_TAGS_ENDPOINT
    )

    payload = {
        "partId": int(part_id),
        "tagIds": [int(tag_id) for tag_id in tag_ids]
    }

    response = connection.session.post(
        url,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("success", False):
        raise RuntimeError(
            "PLM server did not confirm tag assignment."
        )

    return result