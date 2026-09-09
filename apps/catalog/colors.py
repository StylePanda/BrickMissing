COLOR_GROUP_ORDER = (
    "BLACK", "WHITE", "GRAY", "RED", "BLUE", "GREEN", "YELLOW", "ORANGE",
    "BROWN", "PURPLE", "TRANS", "METALLIC / PEARL / FLAT", "OTHER",
)


def normalized_color_name(name: str) -> str:
    """Return the shared comparison key without changing the stored color."""
    return " ".join((name or "").strip().casefold().replace("-", " ").split())


def color_category(name: str) -> str:
    value = normalized_color_name(name)
    words = set(value.split())
    if value.startswith("trans ") or "transparent" in words:
        return "TRANS"
    if words & {"metallic", "pearl", "flat"}:
        return "METALLIC / PEARL / FLAT"
    if words & {"nougat", "brown", "tan", "copper"}:
        return "BROWN"
    if words & {"lime", "green", "olive"}:
        return "GREEN"
    if words & {"gray", "grey"}:
        return "GRAY"
    if "black" in words:
        return "BLACK"
    if words & {"white", "milky"}:
        return "WHITE"
    if words & {"blue", "azure", "aqua", "turquoise"}:
        return "BLUE"
    if words & {"red", "coral", "pink"}:
        return "RED"
    if words & {"yellow", "gold"}:
        return "YELLOW"
    if "orange" in words:
        return "ORANGE"
    if words & {"purple", "violet", "lavender", "magenta"}:
        return "PURPLE"
    return "OTHER"


def resolve_color_values(selected, available):
    """Resolve UI values to exact stored values using the central color rules.

    Exact normalized names win. A category label is expanded only when it is
    not itself an available color name. Unknown values remain unmatched rather
    than silently disabling an active filter.
    """
    available = tuple(dict.fromkeys(value for value in available if normalized_color_name(value)))
    resolved = []
    for selection in dict.fromkeys(value for value in selected if normalized_color_name(value)):
        key = normalized_color_name(selection)
        matches = [value for value in available if normalized_color_name(value) == key]
        if not matches:
            category = next(
                (label for label in COLOR_GROUP_ORDER if normalized_color_name(label) == key),
                None,
            )
            if category is not None:
                matches = [value for value in available if color_category(value) == category]
        resolved.extend(matches or [selection.strip()])
    return list(dict.fromkeys(resolved))


def grouped_colors(values):
    grouped = {}
    for value in values:
        display = "Keine Farbangabe" if value == "[No Color/Any Color]" else value
        grouped.setdefault(color_category(value), []).append({"value": value, "label": display})
    return [
        {"label": label, "colors": grouped[label]}
        for label in COLOR_GROUP_ORDER
        if label in grouped
    ]
