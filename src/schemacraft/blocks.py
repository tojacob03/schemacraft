"""Translate a city plan into Minecraft blocks.

The result is a list of fill/set operations (later ones win) plus sign block
entities, bucketed by chunk so world and schematic export can rasterise any box.
Coordinates: city x/z are world x/z; the ground is the grass layer of a
superflat world (bedrock, dirt, dirt, grass from y=-64), buildings start on top.
"""

import json
import random
from collections import defaultdict

import numpy as np

from schemacraft.layout import key

GROUND_Y = -61  # grass layer of the superflat world
BASE_Y = GROUND_Y + 1  # first block above ground
FLOOR_EVERY = 4
LAMP_EVERY = 8

WALL = "minecraft:stone_bricks"
CRACKED = "minecraft:cracked_stone_bricks"
VIEW_WALL = "minecraft:light_blue_stained_glass"
WINDOW = "minecraft:glass"
SLAB = "minecraft:smooth_stone"
LIGHT = "minecraft:sea_lantern"
FLOOR = "minecraft:polished_andesite"
ROAD = "minecraft:polished_andesite"
DARK_ROAD = "minecraft:blackstone"
POST = "minecraft:oak_fence"
LAMP = "minecraft:lantern[hanging=false]"
ROOFS = [  # one per schema
    "minecraft:cyan_terracotta", "minecraft:orange_terracotta", "minecraft:lime_terracotta",
    "minecraft:magenta_terracotta", "minecraft:yellow_terracotta", "minecraft:light_blue_terracotta",
    "minecraft:red_terracotta", "minecraft:purple_terracotta",
]
SIGN_LINE = 15  # characters that fit on one sign line


class Blocks:
    def __init__(self):
        self.states = ["minecraft:air"]
        self._ids = {"minecraft:air": 0}
        self.ops: dict = defaultdict(list)  # chunk -> [(x0, y0, z0, x1, y1, z1, state id)], inclusive
        self.sequence: list = []  # every op once, in order
        self.entities: dict = defaultdict(list)  # chunk -> [block entity]
        self.max_y = GROUND_Y

    def id(self, state: str) -> int:
        if state not in self._ids:
            self._ids[state] = len(self.states)
            self.states.append(state)
        return self._ids[state]

    def fill(self, x0, y0, z0, x1, y1, z1, state: str) -> None:
        op = (x0, y0, z0, x1, y1, z1, self.id(state))
        self.sequence.append(op)
        for cx in range(x0 >> 4, (x1 >> 4) + 1):
            for cz in range(z0 >> 4, (z1 >> 4) + 1):
                self.ops[(cx, cz)].append(op)
        self.max_y = max(self.max_y, y1)

    def set(self, x, y, z, state: str) -> None:
        self.fill(x, y, z, x, y, z, state)

    def sign(self, x, y, z, facing: str | None, lines: list[str]) -> None:
        """Wall sign facing a direction, or a standing sign when facing is None."""
        state = f"minecraft:oak_wall_sign[facing={facing}]" if facing else "minecraft:oak_sign[rotation=0]"
        self.set(x, y, z, state)
        messages = [json.dumps({"text": s}) for s in (lines + [""] * 4)[:4]]
        self.entities[(x >> 4, z >> 4)].append({
            "id": "minecraft:sign", "x": x, "y": y, "z": z, "is_waxed": True,
            "front_text": {"messages": messages, "color": "black", "has_glowing_text": False},
            "back_text": {"messages": [json.dumps("")] * 4, "color": "black", "has_glowing_text": False},
        })

    def raster(self, ops, x0, y0, z0, sx, sy, sz, base=None) -> np.ndarray:
        """Block ids for the box starting at (x0, y0, z0), indexed [y, z, x]."""
        arr = np.zeros((sy, sz, sx), np.uint16) if base is None else base
        for ax, ay, az, bx, by, bz, sid in ops:
            lx, ly, lz = max(ax, x0), max(ay, y0), max(az, z0)
            hx, hy, hz = min(bx, x0 + sx - 1), min(by, y0 + sy - 1), min(bz, z0 + sz - 1)
            if lx <= hx and ly <= hy and lz <= hz:
                arr[ly - y0:hy - y0 + 1, lz - z0:hz - z0 + 1, lx - x0:hx - x0 + 1] = sid
        return arr

    def bounds(self) -> tuple[int, int, int, int]:
        """x0, z0, x1, z1 of everything placed, inclusive."""
        return (
            min(op[0] for op in self.sequence), min(op[2] for op in self.sequence),
            max(op[3] for op in self.sequence), max(op[5] for op in self.sequence),
        )


def build(model: dict, city: dict, name: str = "schemacraft") -> tuple[Blocks, tuple[int, int, int]]:
    """Return the blocks of the whole city and the spawn point."""
    blocks = Blocks()
    tables = {key(t): t for t in model["tables"]}
    schemas = sorted({str(t["schema"]) for t in model["tables"]})
    buildings = {b["table"]: b for b in city["buildings"]}

    doors = defaultdict(set)  # table -> wall cells that get an opening
    for road in city["roads"]:
        for table, end in ((road["from"], road["cells"][0]), (road["to"], road["cells"][-1])):
            doors[table].add(_door_cell(buildings[table], tuple(end)))

    occupied = _roads(blocks, city)
    for k, b in buildings.items():
        roof = ROOFS[schemas.index(str(b["schema"])) % len(ROOFS)]
        _building(blocks, b, tables[k], roof, doors[k] or {(b["x"] + b["w"] // 2, b["z"] + b["d"] - 1)})

    spawn = _spawn(city)
    w, d = city["size"]
    free = [
        (x, z) for x in range(spawn[0] - 8, spawn[0] + 9) for z in range(spawn[2] - 8, spawn[2] + 9)
        if (x, z) not in occupied and 0 <= x < w and 0 <= z < d
    ]
    if free:  # welcome sign on the nearest free ground
        x, z = min(free, key=lambda c: ((c[0] - spawn[0]) ** 2 + (c[1] - spawn[2]) ** 2, c))
        blocks.sign(x, BASE_Y, z, None,
                    ["schemacraft", name[:SIGN_LINE], f"{len(buildings)} tables", f"{len(city['roads'])} roads"])
    return blocks, spawn


def _door_cell(b, outside):
    """Wall cell next to a road end, kept two blocks from the corners.

    That keeps doors clear of the walls meeting at the corner and of the ladder in the inner corner.
    """
    ox, oz = outside
    x0, z0, x1, z1 = b["x"], b["z"], b["x"] + b["w"] - 1, b["z"] + b["d"] - 1
    x, z = min(max(ox, x0), x1), min(max(oz, z0), z1)
    if z in (z0, z1):
        x = min(max(x, x0 + 2), x1 - 2)
    if x in (x0, x1):
        z = min(max(z, z0 + 2), z1 - 2)
    return x, z


def _building(blocks: Blocks, b: dict, table: dict, roof: str, doors: set) -> None:
    x0, z0, x1, z1 = b["x"], b["z"], b["x"] + b["w"] - 1, b["z"] + b["d"] - 1
    y0, y1 = BASE_Y, BASE_Y + b["h"] - 1
    is_view = table["kind"] == "view"
    wall = VIEW_WALL if is_view else WALL

    blocks.fill(x0, GROUND_Y, z0, x1, GROUND_Y, z1, FLOOR)
    blocks.fill(x0, y0, z0, x1, y1, z1, wall)
    blocks.fill(x0 + 1, y0, z0 + 1, x1 - 1, y1 - 1, z1 - 1, "minecraft:air")
    blocks.fill(x0, y1, z0, x1, y1, z1, roof)

    levels = list(range(y0, y1 - 1, FLOOR_EVERY))  # walking height of every storey
    cx, cz = (x0 + x1) // 2, (z0 + z1) // 2
    for y in levels[1:]:
        blocks.fill(x0 + 1, y - 1, z0 + 1, x1 - 1, y - 1, z1 - 1, SLAB)
    for y in levels[1:] + [y1 + 1]:
        blocks.set(cx, y - 1, cz, LIGHT)  # lights the storey below and above
    blocks.fill(x0 + 1, y0, z0 + 1, x0 + 1, y1 - 1, z0 + 1, "minecraft:ladder[facing=south]")

    if not is_view:
        nulls = [c.get("null_fraction", 0.0) for c in table["columns"]]
        crack = sum(nulls) / len(nulls) if nulls else 0.0
        rnd = random.Random(b["table"])
        for x, z in _ring_cells(x0, z0, x1, z1):
            for y in range(y0, y1):
                if rnd.random() < crack:
                    blocks.set(x, y, z, CRACKED)
        for y in levels:
            if y + 2 < y1:
                for i, (x, z) in enumerate(_ring_cells(x0, z0, x1, z1)):
                    if i % 3 == 1 and not _is_corner(x, z, x0, z0, x1, z1):
                        blocks.set(x, y + 2, z, WINDOW)

    for x, z in doors:
        blocks.fill(x, y0, z, x, y0 + 1, z, "minecraft:air")
        facing, (dx, dz) = _outward(x, z, x0, z0, x1, z1)
        blocks.sign(x + dx, y0 + 2, z + dz, facing, _title(b, table))

    _column_signs(blocks, table, x0, z0, x1, z1, levels, doors)


def _title(b, table) -> list[str]:
    lines = _wrap(table["name"], 2)
    if table["schema"]:
        lines = [table["schema"][:SIGN_LINE]] + lines[:1]
    rows = "view" if b["rows"] is None else f"{b['rows']:,} rows" + ("~" if table.get("row_count_estimated") else "")
    return lines + [rows, f"{b['columns']} columns"]


def _column_signs(blocks, table, x0, z0, x1, z1, levels, doors) -> None:
    fk_cols = {c for fk in table["foreign_keys"] for c in fk["columns"]}
    blocked = {(x0 + 1, z0 + 1)}  # ladder
    for x, z in doors:
        _, (dx, dz) = _outward(x, z, x0, z0, x1, z1)
        blocked.add((x - dx, z - dz))
    slots = [(c, f) for c, f in _inner_ring(x0, z0, x1, z1) if c not in blocked]
    places = [(x, y + 1, z, f) for y in levels for (x, z), f in slots]
    cols = table["columns"]
    if len(cols) > len(places):
        cols, rest = cols[: len(places) - 1], len(cols) - len(places) + 1
    else:
        rest = 0
    for (x, y, z, facing), col in zip(places, cols):
        flags = " ".join(f for f, on in (("PK", col["primary_key"]), ("FK", col["name"] in fk_cols)) if on)
        nulls = col.get("null_fraction")
        if nulls:
            flags = f"{flags} {round(nulls * 100)}% null".strip()
        blocks.sign(x, y, z, facing, _wrap(col["name"], 2) + [col["type"][:SIGN_LINE].lower(), flags])
    if rest:
        x, y, z, facing = places[len(cols)]
        blocks.sign(x, y, z, facing, ["", f"+{rest} more", "columns"])


def _wrap(text: str, max_lines: int) -> list[str]:
    parts = [text[i:i + SIGN_LINE] for i in range(0, len(text), SIGN_LINE)] or [""]
    return parts[:max_lines]


def _ring_cells(x0, z0, x1, z1) -> list:
    """Wall cells clockwise from the north-west corner."""
    return (
        [(x, z0) for x in range(x0, x1)] + [(x1, z) for z in range(z0, z1)]
        + [(x, z1) for x in range(x1, x0, -1)] + [(x0, z) for z in range(z1, z0, -1)]
    )


def _inner_ring(x0, z0, x1, z1) -> list:
    """Cells along the inside of the walls, with the direction a wall sign there faces."""
    cells = [((x, z0 + 1), "south") for x in range(x0 + 1, x1)]
    cells += [((x1 - 1, z), "west") for z in range(z0 + 2, z1)]
    cells += [((x, z1 - 1), "north") for x in range(x1 - 2, x0, -1)]
    cells += [((x0 + 1, z), "east") for z in range(z1 - 2, z0 + 1, -1)]
    return cells


def _is_corner(x, z, x0, z0, x1, z1) -> bool:
    return x in (x0, x1) and z in (z0, z1)


def _outward(x, z, x0, z0, x1, z1):
    if z == z0:
        return "north", (0, -1)
    if z == z1:
        return "south", (0, 1)
    if x == x0:
        return "west", (-1, 0)
    return "east", (1, 0)


def _free_neighbour(x, z, occupied, size):
    w, d = size
    return next(
        ((x + dx, z + dz) for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))
         if (x + dx, z + dz) not in occupied and 0 <= x + dx < w and 0 <= z + dz < d),
        None,
    )


def _roads(blocks: Blocks, city: dict) -> set:
    """Pave the roads and put up lamps; return the cells that are now taken."""
    lit = {tuple(c) for r in city["roads"] if r["indexed"] for c in r["cells"]}
    cells = {tuple(c) for r in city["roads"] for c in r["cells"]}
    for x, z in cells:
        blocks.set(x, GROUND_Y, z, ROAD if (x, z) in lit else DARK_ROAD)

    occupied = set(cells) | {
        (x, z)
        for b in city["buildings"]
        for x in range(b["x"] - 1, b["x"] + b["w"] + 1)
        for z in range(b["z"] - 1, b["z"] + b["d"] + 1)
    }
    for road in city["roads"]:
        for x, z in road["cells"][LAMP_EVERY // 2::LAMP_EVERY]:
            spot = _free_neighbour(x, z, occupied, city["size"])
            if spot:
                occupied.add(spot)
                blocks.set(spot[0], BASE_Y, spot[1], POST)
                if road["indexed"]:
                    blocks.set(spot[0], BASE_Y + 1, spot[1], LAMP)  # unindexed foreign keys: a broken lamp
    return occupied


def _spawn(city: dict) -> tuple[int, int, int]:
    """A road cell close to the centre, or the corner if the city has no roads."""
    w, d = city["size"]
    cells = [tuple(c) for r in city["roads"] for c in r["cells"]]
    if not cells:
        return 1, BASE_Y, 2
    x, z = min(cells, key=lambda c: ((c[0] - w / 2) ** 2 + (c[1] - d / 2) ** 2, c))
    return x, BASE_Y, z
