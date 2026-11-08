"""Terrain for a preset: elevation, sea, rivers, moisture, biomes and fertility.

Layered, all in numpy:
  elevation  multi-octave value noise + the preset's mountain ranges, falling toward its sea
  rivers     the preset's river courses, wiggled by noise and widening downstream
  moisture   the region's rainfall + noise + wetness spreading out from rivers - its deserts
  biomes     from elevation and moisture: sea, river, snow, mountain, hills, desert, forest, marsh, plains
  fertility  what a farm on that tile yields: river plains best, deserts and peaks worst
"""

from dataclasses import dataclass

import numpy as np

from .presets import PRESETS

W, H = 128, 84
BIOMES = ["sea", "river", "snow", "mountain", "hills", "desert", "forest", "marsh", "plains"]
B = {name: i for i, name in enumerate(BIOMES)}
FERTILITY = {
    "sea": 0.0,
    "river": 0.0,
    "snow": 0.0,
    "mountain": 0.05,
    "hills": 0.45,
    "desert": 0.08,
    "forest": 0.4,
    "marsh": 0.5,
    "plains": 0.8,
}


def value_noise(rng: np.random.Generator, octaves: int = 4) -> np.ndarray:
    out = np.zeros((H, W))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = 3 * 2**o
        grid = rng.random((cells + 2, cells + 2))
        ys = np.linspace(0, cells, H)
        xs = np.linspace(0, cells, W)
        y0, x0 = ys.astype(int), xs.astype(int)
        fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)  # smoothstep
        a = grid[np.ix_(y0, x0)]
        b = grid[np.ix_(y0, x0 + 1)]
        c = grid[np.ix_(y0 + 1, x0)]
        d = grid[np.ix_(y0 + 1, x0 + 1)]
        out += amp * ((a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy)
        total += amp
        amp *= 0.5
    return out / total


def blob(cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    ys, xs = np.mgrid[0:H, 0:W]
    return np.exp(-(((xs / W - cx) / max(rx, 1e-3)) ** 2 + ((ys / H - cy) / max(ry, 1e-3)) ** 2) * 2.5)


def sea_gradient(side: str) -> np.ndarray:
    ys, xs = np.mgrid[0:H, 0:W]
    x, y = xs / (W - 1), ys / (H - 1)
    return {
        "north": 1 - y,
        "south": y,
        "east": x,
        "west": 1 - x,
        "southwest": np.clip((y + (1 - x)) / 2, 0, 1),
        "southeast": np.clip((y + x) / 2, 0, 1),
    }[side]


def river_path(points: list, rng: np.random.Generator) -> list[tuple[float, float]]:
    """Smooth meanders through the control points, in tile coordinates.

    A Catmull-Rom curve through the points, displaced sideways by two low-frequency
    sine waves, so the river bends like a real one instead of zigzagging.
    """
    pts = [(x * (W - 1), y * (H - 1)) for x, y in points]
    pts = [pts[0], *pts, pts[-1]]
    phase1, phase2 = rng.random() * 6.28, rng.random() * 6.28
    path, travelled = [], 0.0
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        seg = max(abs(p2[0] - p1[0]), abs(p2[1] - p1[1]))
        steps = int(seg * 2) + 2
        for t in np.linspace(0, 1, steps, endpoint=False):
            t2, t3 = t * t, t * t * t
            x = 0.5 * (
                2 * p1[0]
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                2 * p1[1]
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            norm = max((dx * dx + dy * dy) ** 0.5, 1e-6)
            travelled += seg / steps
            sway = 1.8 * np.sin(travelled / 6.0 + phase1) + 0.8 * np.sin(travelled / 2.7 + phase2)
            path.append((float(x - dy / norm * sway), float(y + dx / norm * sway)))
    path.append(pts[-1])
    return path


@dataclass
class Terrain:
    preset: str
    elevation: np.ndarray
    moisture: np.ndarray
    biome: np.ndarray
    fertility: np.ndarray
    river_dist: np.ndarray
    rivers: list  # list of paths in tile coordinates, for the client to draw flowing water

    def land(self) -> np.ndarray:
        return (self.biome != B["sea"]) & (self.biome != B["river"])

    def to_client(self) -> dict:
        return {
            "width": W,
            "height": H,
            "biomes": BIOMES,
            "biome": self.biome.flatten().tolist(),
            "elevation": np.round(self.elevation, 3).flatten().tolist(),
            "moisture": np.round(self.moisture, 3).flatten().tolist(),
            "rivers": [[(round(x, 2), round(y, 2)) for x, y in path] for path in self.rivers],
        }


def generate(preset_id: str, seed: int) -> Terrain:
    p = PRESETS[preset_id]
    rng = np.random.default_rng(seed)
    elev = 0.45 * value_noise(rng) + 0.1
    for cx, cy, rx, ry in p["mountains"]:
        elev += 0.75 * blob(cx, cy, rx, ry) * (0.7 + 0.6 * value_noise(rng, 3))
    elev -= 0.55 * sea_gradient(p["sea"]) ** 3
    elev = np.clip(elev, 0, 1)

    biome = np.full((H, W), B["plains"])
    sea = elev < 0.12
    biome[sea] = B["sea"]

    river = np.zeros((H, W), dtype=bool)
    paths = []
    for course in p["rivers"]:
        path = river_path(course, rng)
        paths.append(path)
        for k, (x, y) in enumerate(path):
            width = 0.6 + 1.2 * k / max(len(path), 1)  # widens downstream
            xi, yi = int(round(x)), int(round(y))
            r = int(np.ceil(width))
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if dx * dx + dy * dy <= width * width and 0 <= yi + dy < H and 0 <= xi + dx < W:
                        river[yi + dy, xi + dx] = True
    river &= ~sea
    biome[river] = B["river"]

    # distance to the nearest river tile, by repeated dilation (cheap at this size)
    dist = np.full((H, W), 99.0)
    frontier = river.copy()
    dist[frontier] = 0
    for d in range(1, 12):
        grown = frontier.copy()
        grown[1:, :] |= frontier[:-1, :]
        grown[:-1, :] |= frontier[1:, :]
        grown[:, 1:] |= frontier[:, :-1]
        grown[:, :-1] |= frontier[:, 1:]
        newly = grown & ~frontier
        dist[newly] = d
        frontier = grown

    moist = p["rain"] + 0.3 * (value_noise(rng, 3) - 0.5) + 0.45 * np.exp(-dist / 3.0)
    for cx, cy, rx, ry in p["deserts"]:
        moist -= 0.7 * blob(cx, cy, rx, ry)
    moist = np.clip(moist, 0, 1)

    land = ~sea & ~river
    biome[land & (moist < 0.2)] = B["desert"]
    groves = value_noise(rng, 3)  # forests grow in patches, with clearings and fields between them
    biome[land & (moist >= 0.55) & (groves > 0.52 - 0.25 * (moist - 0.55))] = B["forest"]
    biome[land & (moist >= 0.78) & (dist <= 3) & (elev < 0.4)] = B["marsh"]
    biome[land & (elev > 0.55)] = B["hills"]
    biome[land & (elev > 0.68)] = B["mountain"]
    biome[land & (elev > 0.86)] = B["snow"]

    fert = np.vectorize(lambda b: FERTILITY[BIOMES[b]])(biome) * (0.6 + 0.4 * moist)
    fert *= 1 + 0.6 * np.exp(-dist / 2.5)  # river plains are the breadbaskets
    return Terrain(preset_id, elev, moist, biome, np.clip(fert, 0, 1.5), dist, paths)
