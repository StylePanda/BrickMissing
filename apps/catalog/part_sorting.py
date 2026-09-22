"""Shared, read-only physical size ordering for catalog and missing parts."""

import re
from fractions import Fraction
from math import isqrt

_NUMBER = r"(?:\d{1,3}(?:\.\d+|/\d+)?)"
_DIMENSIONS = re.compile(
    rf"(?<!\w)({_NUMBER})\s*[x\u00d7]\s*({_NUMBER})(?:\s*[x\u00d7]\s*({_NUMBER}))?(?![\w/])",
    re.IGNORECASE,
)
_LENGTH_L = re.compile(r"(?<!\w)(\d{1,2})\s*L\b", re.IGNORECASE)
_NAMED_LENGTH = re.compile(r"\b(?:axle|beam|liftarm|hose|bar)\s+(\d{1,2})\b", re.IGNORECASE)
_LENGTH_CONTEXT = re.compile(r"\b(?:technic|axle|beam|liftarm|hose|bar)\b", re.IGNORECASE)
_WORDS = re.compile(r"[a-z0-9]+")
_PLURAL_FAMILIES = {
    "arches": "arch", "axles": "axle", "beams": "beam", "bricks": "brick",
    "connectors": "connector", "gears": "gear", "liftarms": "liftarm",
    "panels": "panel", "pins": "pin", "plates": "plate", "slopes": "slope",
    "tiles": "tile", "tires": "tire", "wedges": "wedge", "wheels": "wheel",
    "wings": "wing", "bases": "base", "bows": "bow", "bars": "bar",
    "hoses": "hose", "baseplates": "base",
}
_FAMILY_RULES = (
    ("technic_liftarm", ("liftarm",)), ("technic_liftarm", ("beam",)),
    ("technic_axle", ("axle",)), ("technic_pin", ("pin",)),
    ("technic_connector", ("connector",)), ("technic_brick", ("technic", "brick")),
    ("brick", ("brick",)), ("plate", ("plate",)), ("tile", ("tile",)),
    ("slope", ("slope",)), ("wedge", ("wedge",)), ("wing", ("wing",)),
    ("arch", ("arch",)), ("panel", ("panel",)), ("base", ("base",)),
    ("bow", ("bow",)), ("bar", ("bar",)), ("hose", ("hose",)),
    ("gear", ("gear",)), ("wheel", ("wheel",)), ("wheel", ("tire",)),
    ("minifigure", ("minifig",)),
)
_FAMILY_ORDER = {
    family: index for index, family in enumerate((
        "brick", "plate", "tile", "slope", "wedge", "wing", "arch",
        "panel", "base", "bow", "technic_brick", "technic_liftarm",
        "technic_axle", "technic_pin", "technic_connector", "bar", "hose",
        "gear", "wheel", "minifigure",
    ))
}


def _normalized(value):
    return " ".join(_WORDS.findall((value or "").casefold()))


def _family_words(value):
    return {_PLURAL_FAMILIES.get(word, word) for word in _WORDS.findall((value or "").casefold())}


def part_form_family(name, category=""):
    """Use local category when supplied, falling back to words in the name."""
    category_words = _family_words(category)
    name_words = _family_words(name)
    for family, required_words in _FAMILY_RULES:
        required = set(required_words)
        if required <= category_words or required <= name_words:
            return family
    fallback = _normalized(category) or next(iter(_WORDS.findall((name or "").casefold())), "unknown")
    return f"other:{fallback}"


def _size_score(dimensions):
    """Score outer extent, footprint, and height without estimating material mass."""
    width, length = (Fraction(1), dimensions[0]) if len(dimensions) == 1 else dimensions[:2]
    height = dimensions[2] if len(dimensions) == 3 else Fraction(1)
    area = width * length
    # 100 * (longest extent + sqrt(footprint) + height / 2).
    footprint = isqrt((10000 * area.numerator) // area.denominator)
    return int(100 * max(width, length, height)) + footprint + int(50 * height)


def parsed_part_dimensions(name):
    """Return (physical score, dimensions), or None if size is unknown."""
    candidates = []
    for match in _DIMENSIONS.finditer(name or ""):
        values = tuple(Fraction(value) for value in match.groups() if value is not None)
        if not all(0 < value <= 96 for value in values):
            continue
        # Rebrickable names commonly give bare tyre/wheel dimensions in mm.
        # Other parts use stud units. The threshold preserves 2 x 2 wheels.
        if re.match(r"^(?:tyre|wheel)\b", name or "", re.IGNORECASE) and max(values) >= 10:
            values = tuple(value / 8 for value in values)
        dimensions = (*sorted(values[:2]), *values[2:])
        candidates.append((_size_score(dimensions), dimensions))
    if candidates:
        return max(candidates)

    if _LENGTH_CONTEXT.search(name or ""):
        lengths = [int(value) for value in _LENGTH_L.findall(name or "")]
        lengths.extend(int(value) for value in _NAMED_LENGTH.findall(name or ""))
        lengths = [value for value in lengths if 0 < value <= 64]
        if lengths:
            length = max(lengths)
            return _size_score((Fraction(length),)), (length,)
    return None

def part_size_form_sort_key(
    name, *, category="", design_id="", part_number="", element_id="",
    color="", descending=False,
):
    """Global size first, family only for identical scores, unknowns last."""
    family = part_form_family(name, category)
    family_key = (_FAMILY_ORDER.get(family, len(_FAMILY_ORDER)), family)
    parsed = parsed_part_dimensions(name)
    if parsed is None:
        size_key = (1, 0, ())
    else:
        score, dimensions = parsed
        size_key = (0, -score if descending else score, dimensions)
    return (
        *size_key, *family_key, _normalized(name), _normalized(design_id),
        _normalized(part_number), _normalized(element_id), _normalized(color),
    )
