"""Google scopes the Agentek integration requests, and tool visibility by granted scopes."""

from auth.scopes import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_SCOPE,
    CONTACTS_SCOPE,
    DOCS_WRITE_SCOPE,
    DRIVE_FILE_SCOPE,
    FORMS_BODY_SCOPE,
    FORMS_RESPONSES_READONLY_SCOPE,
    OPENID_SCOPE,
    SHEETS_WRITE_SCOPE,
    SLIDES_SCOPE,
    TASKS_SCOPE,
    USERINFO_EMAIL_SCOPE,
)

SERVICES = [
    "drive",
    "docs",
    "sheets",
    "slides",
    "calendar",
    "contacts",
    "tasks",
    "forms",
]
IDENTITY_SCOPES = [OPENID_SCOPE, USERINFO_EMAIL_SCOPE]
SERVICE_SCOPES = [
    DRIVE_FILE_SCOPE,
    DOCS_WRITE_SCOPE,
    SHEETS_WRITE_SCOPE,
    SLIDES_SCOPE,
    CALENDAR_SCOPE,
    CALENDAR_EVENTS_SCOPE,
    CONTACTS_SCOPE,
    TASKS_SCOPE,
    FORMS_BODY_SCOPE,
    FORMS_RESPONSES_READONLY_SCOPE,
]
REQUESTED_SCOPES = [*IDENTITY_SCOPES, *SERVICE_SCOPES]

_GOOGLE = "https://www.googleapis.com/auth/"
# Upstream declares `drive.readonly` and `drive` on Drive tools, yet they work with `drive.file`
# within the integration's own files — so visibility compares APIs, not exact scopes.
_API_OF_SCOPE_PREFIX = {
    "drive": "drive",
    "documents": "docs",
    "spreadsheets": "sheets",
    "presentations": "slides",
    "calendar": "calendar",
    "contacts": "contacts",
    "tasks": "tasks",
    "forms": "forms",
}


# Tools that work without the Drive API thanks to agentek/drive_fallback.py.
REQUIRED_SCOPES_OVERRIDE = {
    "get_doc_content": [f"{_GOOGLE}documents.readonly"],
    "get_doc_as_markdown": [f"{_GOOGLE}documents.readonly"],
}


def api_of(scope: str) -> str | None:
    if not scope.startswith(_GOOGLE):
        return None
    name = scope.removeprefix(_GOOGLE).split(".")[0]
    return _API_OF_SCOPE_PREFIX.get(name)


def granted_apis(scopes: list[str]) -> set[str]:
    return {api for api in map(api_of, scopes) if api}


def tool_visible(required_scopes: list[str], granted: set[str]) -> bool:
    return all(api_of(scope) in granted for scope in required_scopes if api_of(scope))
