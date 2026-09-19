"""
Error types used across the engine.

Every failure mode has a machine-readable `code` so a future HTTP/JSON layer can
map it to a status code without parsing English text.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for every expected (non-crash) failure."""

    code = "app_error"

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "detail": self.detail,
            },
        }


# -- configuration ---------------------------------------------------------
class ConfigError(AppError):
    code = "config_error"


class MissingAPIKeyError(ConfigError):
    code = "missing_api_key"


# -- input / files ---------------------------------------------------------
class FileNotFoundErrorApp(AppError):
    code = "file_not_found"


class UnsupportedFileError(AppError):
    code = "unsupported_file_type"


class EmptyContentError(AppError):
    code = "empty_content"


class ExtractionError(AppError):
    code = "extraction_failed"


class ScannedDocumentError(ExtractionError):
    code = "scanned_document"


class CorruptFileError(ExtractionError):
    code = "corrupt_file"


# -- model / provider ------------------------------------------------------
class ProviderError(AppError):
    code = "provider_error"


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"


class ContextLimitError(ProviderError):
    code = "context_limit"


class ModelResponseError(AppError):
    """The model answered, but the answer could not be used."""

    code = "invalid_model_response"


# -- export ----------------------------------------------------------------
class ExportError(AppError):
    code = "export_failed"


def sanitize(text: str, secret: str | None) -> str:
    """Remove a secret value from any string before it is shown or logged."""
    if not text:
        return ""
    if secret and len(secret) > 4 and secret in text:
        text = text.replace(secret, "***REDACTED***")
    return text
