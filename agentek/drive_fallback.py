"""Workarounds for drive.file: Docs and Sheets open shared documents by ID, while the Drive API
returns 404 for their metadata and comments (the file was not created by the integration)."""

import asyncio
from typing import Any

from googleapiclient.errors import HttpError

GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"


async def document_metadata(
    drive_service: Any, docs_service: Any, document_id: str
) -> dict:
    """File metadata from Drive; for a document outside drive.file, from the Docs API."""
    try:
        return await asyncio.to_thread(
            drive_service.files()
            .get(
                fileId=document_id,
                fields="id, name, mimeType, webViewLink, size",
                supportsAllDrives=True,
            )
            .execute
        )
    except HttpError as error:
        if error.resp.status != 404:
            raise
    document = await asyncio.to_thread(
        docs_service.documents().get(documentId=document_id, fields="title").execute
    )
    return {
        "id": document_id,
        "name": document.get("title", "Unknown File"),
        "mimeType": GOOGLE_DOC_MIME_TYPE,
        "webViewLink": f"https://docs.google.com/document/d/{document_id}/edit",
    }


def is_not_found(error: HttpError) -> bool:
    return error.resp.status == 404
