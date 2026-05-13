"""Canonical upload-validation helper.

Centralizes the file-upload security checks required by
[AGENTS.md → Secure Coding Standards → Rule 1](../../../AGENTS.md#rule-1--file-uploads):

    * `secure_filename` on the client-supplied name
    * extension allow-list (jpg / jpeg / png / gif / webp by default)
    * server-side size cap
    * `PIL.Image.open(...).verify()` content validation
    * explicit handling of `UnidentifiedImageError` and
      `Image.DecompressionBombError`

All upload sites should call :func:`validate_uploaded_image` instead of
re-implementing these checks. The function leaves the file stream rewound to
position 0 on success so the caller can save / forward the bytes.
"""
from __future__ import annotations

import io
from typing import Iterable, Optional, Tuple

from PIL import Image, UnidentifiedImageError
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


# Defaults align with the rest of the app (10 MB per image, common image types).
DEFAULT_ALLOWED_EXTENSIONS: frozenset = frozenset({'jpg', 'jpeg', 'png', 'gif', 'webp'})
DEFAULT_MAX_BYTES: int = 10 * 1024 * 1024


class UploadValidationError(ValueError):
    """Raised when an uploaded file fails security validation.

    The :attr:`status_code` attribute is the HTTP status the caller should
    return to the client (400 for client errors, 413 for size-limit hits).
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _stream_size(stream) -> int:
    """Return the size in bytes of a seekable file-like stream, then rewind it."""
    try:
        stream.seek(0, io.SEEK_END)
        size = stream.tell()
    finally:
        stream.seek(0)
    return size


def validate_uploaded_image(
    file_storage: FileStorage,
    *,
    allowed_extensions: Optional[Iterable[str]] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Tuple[str, str]:
    """Validate a single uploaded image and return ``(safe_name, ext)``.

    Performs (in order):

    1. ``secure_filename`` on the client-supplied filename.
    2. Extension allow-list check (case-insensitive).
    3. Server-side size cap.
    4. ``PIL.Image.open(stream).verify()`` — rejects truncated, corrupt, and
       non-image files even if the extension looks correct.

    On success the file stream is rewound to position 0 and the function
    returns the sanitized filename and lower-case extension. On failure an
    :class:`UploadValidationError` is raised; callers should map
    ``error.status_code`` to the JSON / HTTP response.

    Note:
        This helper does **not** decide the stored filename or S3 key. Callers
        must still generate a non-user-controlled name (e.g. ``f"{sku}_{idx}.jpg"``
        or :func:`app.utils.helpers.generate_unique_filename`) before saving.

    Args:
        file_storage: A Werkzeug ``FileStorage`` (e.g. ``request.files['x']``).
        allowed_extensions: Iterable of allow-listed extensions without dots.
            Defaults to :data:`DEFAULT_ALLOWED_EXTENSIONS`.
        max_bytes: Maximum allowed size in bytes. Defaults to
            :data:`DEFAULT_MAX_BYTES`.

    Returns:
        Tuple of ``(safe_filename, extension)`` where ``safe_filename`` is the
        ``secure_filename`` output and ``extension`` is lower-case without a
        leading dot.

    Raises:
        UploadValidationError: If any check fails. ``.status_code`` is 413 for
            size violations and 400 for everything else.
    """
    if file_storage is None or not getattr(file_storage, 'filename', None):
        raise UploadValidationError('No file provided')

    allow = {e.lower().lstrip('.') for e in (allowed_extensions or DEFAULT_ALLOWED_EXTENSIONS)}

    safe_name = secure_filename(file_storage.filename or '')
    if not safe_name or '.' not in safe_name:
        raise UploadValidationError('Invalid filename')
    ext = safe_name.rsplit('.', 1)[1].lower()
    if ext not in allow:
        raise UploadValidationError(
            f'Unsupported image type: .{ext}. Allowed: {", ".join(sorted(allow))}'
        )

    stream = file_storage.stream
    try:
        size = _stream_size(stream)
    except Exception as exc:
        raise UploadValidationError('Could not read upload') from exc
    if size <= 0:
        raise UploadValidationError('Empty file')
    if size > max_bytes:
        raise UploadValidationError(
            f'File exceeds {max_bytes // (1024 * 1024)}MB limit',
            status_code=413,
        )

    # Pillow content validation. Image.verify() does not fully decode but it
    # does parse headers and detect truncation / decompression bombs. We catch
    # the specific Pillow exceptions plus a final broad `Exception` because
    # Pillow occasionally raises plain `OSError` / `SyntaxError` for malformed
    # files. After verify(), the stream must be rewound for the caller.
    try:
        img = Image.open(stream)
        img.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise UploadValidationError('Invalid or unsafe image') from exc
    except Exception as exc:
        raise UploadValidationError('Invalid image') from exc
    finally:
        try:
            stream.seek(0)
        except Exception:
            pass

    return safe_name, ext

