import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LabelConfiguration:
    rows: int
    columns: int
    margin_top: float
    margin_right: float
    margin_bottom: float
    margin_left: float
    qr_code: bool
    text: str


@dataclass(frozen=True)
class LabelPrintLayout:
    configuration: LabelConfiguration
    orientation: str
    width_mm: float
    height_mm: float


def _bounded_integer(value, default, minimum, maximum):
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return min(max(parsed, minimum), maximum)


def _bounded_number(value, default, minimum, maximum):
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return min(max(parsed, minimum), maximum)


def _boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "ja"}:
            return True
        if normalized in {"", "0", "false", "no", "off", "nein"}:
            return False
    return False


def normalize_label_configuration(raw_configuration):
    raw = raw_configuration if isinstance(raw_configuration, dict) else {}
    text = raw.get("text", "")
    if text is None:
        text = ""
    elif not isinstance(text, str):
        text = str(text)
    return LabelConfiguration(
        rows=_bounded_integer(raw.get("rows", 4), 4, 1, 20),
        columns=_bounded_integer(raw.get("columns", 2), 2, 1, 10),
        margin_top=_bounded_number(raw.get("margin_top", 0), 0, 0, 50),
        margin_right=_bounded_number(raw.get("margin_right", 0), 0, 0, 50),
        margin_bottom=_bounded_number(raw.get("margin_bottom", 0), 0, 0, 50),
        margin_left=_bounded_number(raw.get("margin_left", 0), 0, 0, 50),
        qr_code=_boolean(raw.get("qr_code", False)),
        text=text,
    )


def label_print_layout(label_template):
    configuration = normalize_label_configuration(label_template.configuration)
    orientation = (
        label_template.orientation
        if label_template.orientation in {"portrait", "landscape"}
        else "portrait"
    )
    page_width, page_height = (210.0, 297.0)
    if orientation == "landscape":
        page_width, page_height = page_height, page_width

    available_width = page_width - configuration.margin_left - configuration.margin_right
    available_height = page_height - configuration.margin_top - configuration.margin_bottom
    width = _bounded_number(label_template.width_mm, 50, 0.1, available_width)
    height = _bounded_number(label_template.height_mm, 30, 0.1, available_height)
    columns = min(configuration.columns, max(math.floor(available_width / width), 1))
    rows = min(configuration.rows, max(math.floor(available_height / height), 1))
    effective_configuration = LabelConfiguration(
        rows=rows,
        columns=columns,
        margin_top=configuration.margin_top,
        margin_right=configuration.margin_right,
        margin_bottom=configuration.margin_bottom,
        margin_left=configuration.margin_left,
        qr_code=configuration.qr_code,
        text=configuration.text,
    )
    return LabelPrintLayout(effective_configuration, orientation, width, height)


def normalize_start(value, capacity):
    return _bounded_integer(value or 1, 1, 1, max(capacity, 1))
