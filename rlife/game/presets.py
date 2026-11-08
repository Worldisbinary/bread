"""Real-world regions and eras to start a world from.

Geography is stylised from the real region (where the river runs, where mountains and
deserts lie, how wet it is), not survey-accurate. Dynasty names are fictional, drawn
from the region's place names for flavour; they do not depict real historical peoples.

Coordinates are normalised: x 0..1 west to east, y 0..1 north to south.
"""

PRESETS = {
    "indus": {
        "name": "Indus Valley",
        "years": (-3000, -1500),
        "default_year": -2500,
        "summary": "A great river runs from the northern mountains to the south-western sea, "
        "with desert to the east and monsoon rains that sometimes fail.",
        "rivers": [
            [(0.72, 0.02), (0.62, 0.25), (0.52, 0.45), (0.38, 0.68), (0.22, 0.95)],
            [(0.95, 0.12), (0.8, 0.3), (0.62, 0.42), (0.52, 0.45)],
        ],
        "mountains": [(0.5, 0.0, 0.55, 0.18), (0.05, 0.35, 0.12, 0.3)],  # (x, y, rx, ry)
        "deserts": [(0.85, 0.65, 0.22, 0.3)],
        "sea": "southwest",
        "rain": 0.45,
        "volatility": 0.35,
        "dynasties": ["Harappa", "Dholavi", "Kalibar", "Lothala", "Rakhiga", "Mohenja", "Sutkag"],
    },
    "nile": {
        "name": "Nile Valley",
        "years": (-3100, -1000),
        "default_year": -2600,
        "summary": "A narrow green ribbon through desert, flowing north into a fertile delta; "
        "life depends on the yearly flood.",
        "rivers": [[(0.52, 1.0), (0.48, 0.75), (0.55, 0.5), (0.47, 0.25), (0.5, 0.08)]],
        "mountains": [(0.92, 0.5, 0.1, 0.35)],
        "deserts": [(0.15, 0.5, 0.3, 0.6), (0.8, 0.6, 0.18, 0.45)],
        "sea": "north",
        "rain": 0.12,
        "volatility": 0.25,
        "dynasties": ["Thinis", "Nekhen", "Memfa", "Abydor", "Waset", "Sais", "Bubast"],
    },
    "mesopotamia": {
        "name": "Mesopotamia",
        "years": (-3500, -500),
        "default_year": -2300,
        "summary": "Two rivers run south-east to the gulf between highlands and desert; "
        "canals and floods decide every harvest.",
        "rivers": [
            [(0.3, 0.0), (0.38, 0.3), (0.5, 0.55), (0.72, 0.85), (0.85, 1.0)],
            [(0.55, 0.0), (0.6, 0.3), (0.65, 0.55), (0.75, 0.85)],
        ],
        "mountains": [(0.95, 0.3, 0.12, 0.4), (0.45, 0.0, 0.3, 0.08)],
        "deserts": [(0.08, 0.7, 0.25, 0.35)],
        "sea": "southeast",
        "rain": 0.25,
        "volatility": 0.3,
        "dynasties": ["Uruk", "Lagas", "Kisha", "Akkar", "Mari", "Eshnun", "Larsa"],
    },
    "ganges": {
        "name": "Ganges Plain",
        "years": (-600, 600),
        "default_year": -400,
        "summary": "A broad, wet plain under the highest mountains, with a river flowing east "
        "to a vast delta and monsoons that can flood or fail.",
        "rivers": [
            [(0.02, 0.35), (0.25, 0.45), (0.5, 0.5), (0.75, 0.6), (0.98, 0.85)],
            [(0.2, 0.0), (0.3, 0.25), (0.42, 0.48)],
        ],
        "mountains": [(0.5, 0.0, 0.7, 0.15), (0.4, 1.0, 0.45, 0.15)],
        "deserts": [(0.02, 0.85, 0.12, 0.2)],
        "sea": "southeast",
        "rain": 0.75,
        "volatility": 0.35,
        "dynasties": ["Magadh", "Kosal", "Vatsa", "Anga", "Kashi", "Vajji", "Panchal"],
    },
    "yellow_river": {
        "name": "Yellow River",
        "years": (-1600, 200),
        "default_year": -1100,
        "summary": "A silt-heavy river winds east across loess plains from the western mountains; "
        "it feeds millions and floods without warning.",
        "rivers": [[(0.0, 0.4), (0.2, 0.2), (0.4, 0.35), (0.55, 0.6), (0.75, 0.5), (1.0, 0.55)]],
        "mountains": [(0.0, 0.7, 0.2, 0.35), (0.5, 0.95, 0.4, 0.1)],
        "deserts": [(0.25, 0.02, 0.3, 0.12)],
        "sea": "east",
        "rain": 0.5,
        "volatility": 0.4,
        "dynasties": ["Shangqiu", "Haojing", "Luoyi", "Yinxu", "Qishan", "Anyang", "Fengxi"],
    },
    "mediterranean": {
        "name": "Mediterranean Coast",
        "years": (-800, 400),
        "default_year": -300,
        "summary": "Hilly coasts around a warm sea, with mountain ranges inland, short rivers "
        "and dry summers.",
        "rivers": [[(0.3, 0.1), (0.35, 0.35), (0.32, 0.6)], [(0.7, 0.05), (0.66, 0.3), (0.68, 0.55)]],
        "mountains": [(0.5, 0.15, 0.5, 0.12), (0.12, 0.4, 0.1, 0.25)],
        "deserts": [(0.9, 0.9, 0.15, 0.12)],
        "sea": "south",
        "rain": 0.4,
        "volatility": 0.25,
        "dynasties": ["Akragas", "Korinth", "Massal", "Syrakos", "Tarent", "Kyrene", "Neapol"],
    },
}


def describe() -> list[dict]:
    return [
        {
            "id": key,
            "name": p["name"],
            "years": p["years"],
            "default_year": p["default_year"],
            "summary": p["summary"],
        }
        for key, p in PRESETS.items()
    ]


def year_label(year: int) -> str:
    return f"{-year} BCE" if year < 0 else f"{year} CE"
