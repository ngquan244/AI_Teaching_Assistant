"""
excel_student_parser
====================

Parse an uploaded ``.xlsx`` file containing two logical columns

    student_code (MSSV)   |   full_name (Họ và tên)

Behavioural rules:

* ``.xlsx`` only — ``.xls`` and ``.csv`` are out of scope for phase 1.
* MSSV must be read as **string**. Excel often coerces a 8-digit MSSV
  to a float (``"22028171.0"``); we strip that ``.0`` suffix.
* Header detection is alias-based and case/diacritic-insensitive.
* Whitespace is trimmed and collapsed (multiple spaces → single).
* Generated email is deterministic: ``f"sv{student_code.lower()}@vnu.edu.vn"``.
* Per-row validation produces a structured ``ParsedRow`` with
  ``is_valid`` + ``error_code`` so the caller can persist invalid rows
  alongside valid ones.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


EMAIL_DOMAIN = "vnu.edu.vn"
STUDENT_CODE_REGEX = re.compile(r"^[A-Za-z0-9]{4,20}$")
_WS_RE = re.compile(r"\s+")
_TRAILING_DOT_ZERO_RE = re.compile(r"\.0+$")

# Header aliases. Keys are normalized (NFKD-stripped, lowercased, collapsed).
_CODE_ALIASES = {
    "ma sinh vien",
    "mssv",
    "ma_sv",
    "student_code",
    "studentcode",
    "code",
    "ma so sinh vien",
}
_NAME_ALIASES = {
    "ho ten",
    "ho va ten",
    "full_name",
    "fullname",
    "name",
    "ten",
    "ho_ten",
    "ho_va_ten",
}


# ── Public types ──────────────────────────────────────────────────────────

@dataclass
class ParsedRow:
    row_number: int
    raw_student_code: str = ""
    raw_full_name: str = ""
    student_code: Optional[str] = None
    full_name: Optional[str] = None
    generated_email: Optional[str] = None
    is_valid: bool = False
    error_code: Optional[str] = None
    message: Optional[str] = None


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    detected_code_column: Optional[str] = None
    detected_name_column: Optional[str] = None
    duplicate_codes_in_file: set[str] = field(default_factory=set)


# ── Normalization helpers ─────────────────────────────────────────────────

def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def _normalize_header(text: object) -> str:
    if text is None:
        return ""
    s = str(text).strip().lower()
    s = _strip_accents(s)
    s = _WS_RE.sub(" ", s)
    return s


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    s = str(value).strip()
    return _WS_RE.sub(" ", s)


def _clean_student_code(value: object) -> str:
    """Strip whitespace and Excel's '.0' float artifact from MSSV."""
    s = _clean_cell(value)
    if not s:
        return ""
    s = _TRAILING_DOT_ZERO_RE.sub("", s)
    # Some locales render "22028171,0"
    if s.endswith(",0"):
        s = s[:-2]
    return s


def _generated_email(student_code: str) -> str:
    return f"sv{student_code.lower()}@{EMAIL_DOMAIN}"


# ── Header detection ──────────────────────────────────────────────────────

def _detect_columns(columns: list[str]) -> tuple[Optional[str], Optional[str]]:
    code_col = name_col = None
    for col in columns:
        norm = _normalize_header(col)
        if code_col is None and norm in _CODE_ALIASES:
            code_col = col
        elif name_col is None and norm in _NAME_ALIASES:
            name_col = col
    return code_col, name_col


# ── Public entrypoint ─────────────────────────────────────────────────────

def parse_student_excel(file_bytes: bytes) -> ParseResult:
    """
    Parse a ``.xlsx`` byte payload into a :class:`ParseResult`.

    Raises:
        ValueError: when the file cannot be opened, has no header row,
            or is missing a required column.
    """
    if not file_bytes:
        raise ValueError("Empty file.")

    try:
        df = pd.read_excel(
            io.BytesIO(file_bytes),
            dtype=str,           # everything as string up front
            engine="openpyxl",
            keep_default_na=False,
        )
    except Exception as exc:
        raise ValueError(f"Không thể đọc file Excel: {exc}") from exc

    if df.empty or df.columns.size == 0:
        raise ValueError("File không có dữ liệu.")

    code_col, name_col = _detect_columns(list(df.columns))
    if not code_col:
        raise ValueError(
            "Không tìm thấy cột MSSV. Header phải là một trong: "
            "Mã sinh viên, MSSV, student_code."
        )
    if not name_col:
        raise ValueError(
            "Không tìm thấy cột Họ tên. Header phải là một trong: "
            "Họ tên, Họ và tên, full_name."
        )

    result = ParseResult(
        detected_code_column=str(code_col),
        detected_name_column=str(name_col),
    )

    seen_codes: dict[str, int] = {}

    for idx, raw in df.iterrows():
        # idx is the pandas RangeIndex; +2 → human row number (1-based + header)
        row_number = int(idx) + 2  # type: ignore[arg-type]

        raw_code_val = raw[code_col]
        raw_name_val = raw[name_col]

        code = _clean_student_code(raw_code_val)
        name = _clean_cell(raw_name_val)

        row = ParsedRow(
            row_number=row_number,
            raw_student_code=str(raw_code_val) if raw_code_val is not None else "",
            raw_full_name=str(raw_name_val) if raw_name_val is not None else "",
        )

        # Skip fully blank rows silently — Excel often has trailing empties.
        if not code and not name:
            continue

        if not code:
            row.error_code = "missing_student_code"
            row.message = "Thiếu MSSV."
            result.rows.append(row)
            continue
        if not name:
            row.student_code = code
            row.error_code = "missing_full_name"
            row.message = "Thiếu họ tên."
            result.rows.append(row)
            continue
        if not STUDENT_CODE_REGEX.match(code):
            row.student_code = code
            row.full_name = name
            row.error_code = "invalid_student_code"
            row.message = (
                "MSSV không hợp lệ (chỉ chấp nhận chữ cái và số, 4–20 ký tự)."
            )
            result.rows.append(row)
            continue
        if code.upper().startswith("PH"):
            row.student_code = code
            row.full_name = name
            row.error_code = "ph_account_blocked"
            row.message = "MSSV bắt đầu bằng PH (phụ huynh/observer) — không được import."
            result.rows.append(row)
            continue
        row.student_code = code
        row.full_name = name
        row.generated_email = _generated_email(code)

        # Duplicate detection (case-insensitive on the cleaned code)
        key = code.lower()
        if key in seen_codes:
            row.error_code = "duplicate_in_file"
            row.message = (
                f"Trùng MSSV với dòng {seen_codes[key]} trong cùng file."
            )
            result.duplicate_codes_in_file.add(code)
        else:
            seen_codes[key] = row_number
            row.is_valid = True

        result.rows.append(row)

    return result


# ── Template builder ──────────────────────────────────────────────────────

def build_template_xlsx() -> bytes:
    """
    Build a minimal ``.xlsx`` template (in-memory) with a single example row.

    Returned bytes are ready to be sent as a FastAPI ``Response``.
    """
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sinh viên"
    ws.append(["MSSV", "Họ và tên"])
    ws.append(["22028171", "Nguyễn Văn A"])

    # Set string format on column A so Excel doesn't coerce 8-digit codes
    # back into floats.
    for cell in ws["A"]:
        cell.number_format = "@"

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 30

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
