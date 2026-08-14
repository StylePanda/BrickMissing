COLOR_GROUP_ORDER = (
    "BLACK", "WHITE", "GRAY", "RED", "BLUE", "GREEN", "YELLOW", "ORANGE",
    "BROWN", "PURPLE", "TRANS", "METALLIC / PEARL / FLAT", "OTHER",
)


def color_category(name: str) -> str:
    value = " ".join((name or "").strip().casefold().replace("-", " ").split())
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
