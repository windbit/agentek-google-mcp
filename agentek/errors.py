"""Google API error texts for the agent in Agentek mode (Russian: shown to Agentek users)."""

FILE_UNAVAILABLE = (
    "Файл недоступен интеграции: она видит Google Документы и Таблицы по ссылке и файлы, созданные агентом. "
    "Попросите пользователя прислать ссылку на документ или таблицу; другие файлы Диска интеграции недоступны."
)
TEMPORARILY_UNAVAILABLE = (
    "Google временно недоступен, повторите позже. Подключение в порядке."
)
ACCESS_DENIED = (
    "Google отказал в доступе: у аккаунта нет прав на этот объект или действие, либо закончилась квота Диска. "
    "Повторный вход не поможет."
)


_enabled = False


def enable() -> None:
    """Turns Agentek texts on; a plain upstream run keeps upstream messages."""
    global _enabled
    _enabled = True


def http_error_message(tool_name: str, status: int) -> str | None:
    """Agent-facing text for a Google response status; None keeps the upstream message."""
    if not _enabled:
        return None
    if status == 404:
        return f"{tool_name}: {FILE_UNAVAILABLE}"
    if status == 403:
        return f"{tool_name}: {ACCESS_DENIED}"
    if status == 429 or status >= 500:
        return f"{tool_name}: {TEMPORARILY_UNAVAILABLE}"
    return None
