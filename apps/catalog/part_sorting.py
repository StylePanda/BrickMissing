import re
from math import prod

_DIMENSIONS = re.compile(r"\b(\d+)\s*[x×]\s*(\d+)(?:\s*[x×]\s*(\d+))?\b", re.IGNORECASE)
_LENGTH_L = re.compile(r"\b(\d+)\s*l\b", re.IGNORECASE)
_NAMED_LENGTH = re.compile(r"\b(?:axle|beam|liftarm)\s+(\d+)\b", re.IGNORECASE)
_WORDS = re.compile(r"[a-z0-9]+")
_PLURAL_FAMILIES = {
    "arches": "arch",
    "axles": "axle",
    "beams": "beam",
    "bricks": "brick",
    "connectors": "connector",
    "gears": "gear",
    "liftarms": "liftarm",
    "panels": "panel",
    "pins": "pin",
    "plates": "plate",
    "slopes": "slope",
    "tiles": "tile",
    "tires": "tire",
    "wedges": "wedge",
    "wheels": "wheel",
}


_FAMILY_RULES = (
    ("technic_liftarm", ("liftarm",)),
    ("technic_liftarm", ("beam",)),
    ("technic_axle", ("axle",)),
    ("technic_pin", ("pin",)),
    ("technic_connector", ("connector",)),
    ("technic_brick", ("technic", "brick")),
    ("brick", ("brick",)),
    ("plate", ("plate",)),
    ("tile", ("tile",)),
    ("slope", ("slope",)),
    ("wedge", ("wedge",)),
    ("arch", ("arch",)),
    ("panel", ("panel",)),
    ("gear", ("gear",)),
    ("wheel", ("wheel",)),
    ("wheel", ("tire",)),
    ("minifigure", ("minifig",)),
)
_FAMILY_ORDER = {
    family: index
    for index, family in enumerate(
        (
            "brick",
            "plate",
            "tile",
            "slope",
            "wedge",
            "arch",
            "panel",
            "technic_brick",
            "technic_liftarm",
            "technic_axle",
            "technic_pin",
            "technic_connector",
            "gear",
            "wheel",
            "minifigure",
        )
    )
}


def _normalized(value):
    return " ".join(_WORDS.findall((value or "").casefold()))


def _family_words(value):
    return {
        _PLURAL_FAMILIES.get(word, word)
        for word in _WORDS.findall((value or "").casefold())
    }


def part_form_family(name, category=""):
    """Return a stable physical family using structured category first when present."""
    category_words = _family_words(category)
    name_words = _family_words(name)
    for family, required_words in _FAMILY_RULES:
        required = set(required_words)
        if required <= category_words or required <= name_words:
            return family
    fallback = _normalized(category)
    if not fallback:
        fallback = next(iter(_WORDS.findall((name or "").casefold())), "unknown")
    return f"other:{fallback}"


def parsed_part_dimensions(name):
    """Return a conservative, comparable metric and dimensions parsed from a part name."""
    dimension_matches = []
    for match in _DIMENSIONS.finditer(name or ""):
        dimensions = tuple(sorted(int(value) for value in match.groups() if value is not None))
        dimension_matches.append((prod(dimensions), dimensions))
    if dimension_matches:
        return max(dimension_matches)

    lengths = [int(value) for value in _LENGTH_L.findall(name or "")]
    if not lengths:
        named = _NAMED_LENGTH.search(name or "")
        if named:
            lengths = [int(named.group(1))]
    if lengths:
        length = max(lengths)
        return length, (length,)
    return None


def part_size_form_sort_key(
    name,
    *,
    category="",
    design_id="",
    part_number="",
    element_id="",
    color="",
    descending=False,
):
    """Build the shared form/size key; descending reverses size, not family order."""
    family = part_form_family(name, category)
    family_key = (_FAMILY_ORDER.get(family, len(_FAMILY_ORDER)), family)
    parsed = parsed_part_dimensions(name)
    if parsed is None:
        size_key = (1, 0, (0, 0, 0))
    else:
        metric, dimensions = parsed
        padded = (*dimensions, *(0 for _ in range(3 - len(dimensions))))[:3]
        direction = -1 if descending else 1
        size_key = (0, direction * metric, tuple(direction * value for value in padded))
    return (
        *family_key,
        *size_key,
        _normalized(name),
        _normalized(design_id),
        _normalized(part_number),
        _normalized(element_id),
        _normalized(color),
    )
