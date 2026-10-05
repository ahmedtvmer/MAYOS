"""HTTP errors carrying a source-selected structured display message."""

from typing import Any

from fastapi import HTTPException

from service.messages import MessageMetadata


class MessageHTTPException(HTTPException):
    """An HTTP exception whose message code is selected where the error occurs."""

    def __init__(
        self,
        status_code: int,
        detail: Any,
        message_metadata: MessageMetadata,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.message_metadata = message_metadata


def message_http_exception(
    status_code: int,
    detail: Any,
    message_metadata: MessageMetadata,
) -> MessageHTTPException:
    """Constructs a source-tagged HTTP refusal without changing its detail."""
    return MessageHTTPException(
        status_code,
        detail,
        message_metadata,
    )
