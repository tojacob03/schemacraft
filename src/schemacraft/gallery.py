"""A gallery world: one wall per question, the answer as a chart on maps and in big floating text.

Spec (JSON):
  {"title": "...", "subtitle": "...",
   "exhibits": [{"question": "...", "answer": "...", "note": "...", "chart": {chart spec, see charts.py}}]}

The gallery runs west to east along a north wall. Every exhibit is a wall of glowing item frames
holding maps (6 x 4 maps = 768 x 512 pixels); above it the question, and the answer in large type.
"""

import json
import uuid

from nbtlib import Byte, Compound, Double, Float, Int, IntArray, List, String

from schemacraft.blocks import BASE_Y, GROUND_Y, Blocks
from schemacraft.charts import render
from schemacraft.mapart import TILE, quantise, tiles

WALL_W, WALL_H = 6, 4  # maps per exhibit wall
STEP = WALL_W + 4  # exhibit width plus the gap to the next one
WALL_Z = 0  # the wall the maps hang on; frames sit one block south of it
DEPTH = 13  # inside depth of the gallery, north to south
CEILING = BASE_Y + 9

FLOOR = "minecraft:smooth_quartz"
WALLS = "minecraft:white_concrete"
LIGHT = "minecraft:sea_lantern"


def build_gallery(spec: dict) -> tuple[Blocks, tuple[int, int, int], float, list]:
    """Blocks with frames, maps and text; the spawn point and the direction to look; chart images."""
    blocks = Blocks()
    exhibits = spec["exhibits"]
    x1 = 2 + STEP * len(exhibits) + 1
    z1 = WALL_Z + DEPTH

    blocks.fill(0, GROUND_Y, WALL_Z, x1, GROUND_Y, z1, FLOOR)
    blocks.fill(0, BASE_Y, WALL_Z, x1, CEILING, z1, WALLS)
    blocks.fill(1, BASE_Y, WALL_Z + 1, x1 - 1, CEILING - 1, z1 - 1, "minecraft:air")
    for x in range(3, x1 - 1, 4):
        for z in range(WALL_Z + 3, z1 - 1, 4):
            blocks.set(x, CEILING, z, LIGHT)
    door = x1 // 2  # entrance in the middle of the south wall
    blocks.fill(door - 1, BASE_Y, z1, door + 1, BASE_Y + 3, z1, "minecraft:air")

    images = []
    for i, ex in enumerate(exhibits):
        left = 3 + STEP * i
        image = render(ex["chart"], WALL_W * TILE, WALL_H * TILE)
        images.append(image)
        for (col, row), tile in tiles(quantise(image)).items():
            blocks.maps.append(tile)
            _frame(blocks, left + col, BASE_Y + WALL_H - row, WALL_Z + 1, len(blocks.maps) - 1)
        centre, room = left + WALL_W / 2, WALL_W + 2  # text may use the wall and one block either side
        _text(blocks, centre, BASE_Y + WALL_H + 2.4, WALL_Z + 1.1, f"{i + 1}. {ex['question']}", 1.2, "#555555", room)
        _text(blocks, centre, BASE_Y + WALL_H + 1.2, WALL_Z + 1.1, ex["answer"], 1.6, "#1d5fa8", room, bold=True)
        if ex.get("note"):
            _text(blocks, centre, BASE_Y + 0.2, WALL_Z + 1.1, ex["note"], 0.6, "#777777", room)

    # the name over the entrance, on the outside of the south wall
    facade = min(x1 - 4, 30)
    _text(blocks, door + 0.5, BASE_Y + 6.2, z1 + 1.05, spec["title"], 2.0, "#222222", facade, bold=True)
    if spec.get("subtitle"):
        _text(blocks, door + 0.5, BASE_Y + 5.0, z1 + 1.05, spec["subtitle"], 1.0, "#555555", facade)
    # New players spawn on the highest surface at the spawn point, so spawn outside, facing the entrance.
    spawn = (door, BASE_Y, z1 + 6)
    return blocks, spawn, 180.0, images


def _uuid(*parts) -> IntArray:
    u = uuid.uuid5(uuid.NAMESPACE_URL, "schemacraft:" + ":".join(map(str, parts))).int
    return IntArray([((u >> s) & 0xFFFFFFFF) - (1 << 32 if (u >> s) & 0x80000000 else 0) for s in (96, 64, 32, 0)])


def _frame(blocks: Blocks, x: int, y: int, z: int, map_id: int) -> None:
    """Invisible glowing item frame on the wall north of (x, y, z), facing south, holding a map."""
    blocks.mobs[(x >> 4, z >> 4)].append(Compound({
        "id": String("minecraft:glow_item_frame"),
        "UUID": _uuid("frame", x, y, z),
        "Pos": List[Double]([Double(x + 0.5), Double(y + 0.5), Double(z + 0.03125)]),
        "Motion": List[Double]([Double(0), Double(0), Double(0)]),
        "Rotation": List[Float]([Float(0), Float(0)]),
        "TileX": Int(x), "TileY": Int(y), "TileZ": Int(z),
        "Facing": Byte(3),  # south
        "Item": Compound({
            "id": String("minecraft:filled_map"), "count": Int(1),
            "components": Compound({"minecraft:map_id": Int(map_id)}),
        }),
        "ItemRotation": Byte(0), "ItemDropChance": Float(0),
        "Fixed": Byte(1), "Invisible": Byte(1), "Invulnerable": Byte(1),
    }))


TEXT_PIXEL = 0.025  # blocks per font pixel of a text display at scale 1


def _text(blocks: Blocks, x: float, y: float, z: float, text: str, scale: float, colour: str, width: float,
          bold=False) -> None:
    """Text standing parallel to the north wall, read from the south, wrapped to `width` blocks, fully lit."""
    s = Float(scale)
    blocks.mobs[(int(x) >> 4, int(z) >> 4)].append(Compound({
        "id": String("minecraft:text_display"),
        "UUID": _uuid("text", x, y, z, text),
        "Pos": List[Double]([Double(x), Double(y), Double(z)]),
        "Motion": List[Double]([Double(0), Double(0), Double(0)]),
        "Rotation": List[Float]([Float(0), Float(0)]),  # yaw 0: faces south
        "text": String(json.dumps({"text": text, "color": colour, "bold": bold})),
        "billboard": String("fixed"),
        "line_width": Int(int(width / (TEXT_PIXEL * scale))),
        "background": Int(0x00000000),
        "shadow": Byte(0), "see_through": Byte(0), "alignment": String("center"),
        "brightness": Compound({"block": Int(15), "sky": Int(15)}),
        "transformation": Compound({
            "translation": List[Float]([Float(0), Float(0), Float(0)]),
            "left_rotation": List[Float]([Float(0), Float(0), Float(0), Float(1)]),
            "scale": List[Float]([s, s, s]),
            "right_rotation": List[Float]([Float(0), Float(0), Float(0), Float(1)]),
        }),
    }))
