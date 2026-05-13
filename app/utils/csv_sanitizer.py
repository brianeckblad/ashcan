"""CSV cell sanitization to prevent spreadsheet formula injection.

Spreadsheet applications (Excel, Google Sheets, LibreOffice Calc) interpret
cells that begin with ``=``, ``+``, ``-``, ``@``, ``\\t``, or ``\\r`` as
formulas. A user-controlled value such as ``=HYPERLINK(...)`` or
``=cmd|' /C calc'!A0`` can exfiltrate data or run commands on the
reviewer's machine.

Apply :func:`sanitize_cell` to every user-controlled string value before
writing it to an exported CSV. The sanitizer prefixes dangerous leading
characters with a single apostrophe, which is rendered as an empty string
by spreadsheets but preserved as a literal by ``csv`` text processors.

Only export-bound writers should use this — the application's own
round-trip inventory ``items.csv`` must NOT be sanitized, because the app
re-reads those values and any prefix would corrupt them in the UI.
"""
from typing import Any, Dict, Iterable


# Characters that spreadsheets treat as formula-initiators when they appear
# as the first character of a cell.
_DANGEROUS_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def sanitize_cell(value: Any) -> Any:
    """Return ``value`` with a leading apostrophe if it would be interpreted
    as a spreadsheet formula.

    Non-string values (ints, floats, None) are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    if value and value[0] in _DANGEROUS_PREFIXES:
        return "'" + value
    return value


def sanitize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new dict with every string value passed through
    :func:`sanitize_cell`.
    """
    return {k: sanitize_cell(v) for k, v in row.items()}


def sanitize_rows(rows: Iterable[Dict[str, Any]]):
    """Generator that yields sanitized rows one at a time (memory-friendly)."""
    for row in rows:
        yield sanitize_row(row)

