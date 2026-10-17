"""A gallery world: one wall per question, the answer as a chart on maps and in big floating text.

Spec (JSON):
  {"title": "...", "subtitle": "...",
   "exhibits": [{"question": "...", "answer": "...", "note": "...", "chart": {chart spec, see charts.py}},
                {"question": "...", "answer": "...", "views": [{"label": "Game 1", "chart": {...}}, ...]}]}

The gallery runs west to east along a north wall. Every exhibit is a wall of glowing item frames
holding maps (6 x 4 maps = 768 x 512 pixels); above it the question, and the answer in large type.
An exhibit with several views gets a button per view in front of it: pressing one runs a chain of
command blocks under the floor that swaps the maps in every frame.

The helpers frame(), text() and command_chain() place the same things anywhere in a world.
"""

import json
import math
import uuid

from nbtlib import Byte, Compound, Double, Float, Int, IntArray, List, Long, String

from schemacraft.blocks import BASE_Y, GROUND_Y, Blocks
from schemacraft.charts import render
from schemacraft.mapart import TILE, quantise, tiles

WALL_W, WALL_H = 6, 4  # maps per exhibit wall
STEP = WALL_W + 4  # exhibit width plus the gap to the next one
WALL_Z = 0  # the wall the maps hang on; frames sit one block south of it
DEPTH = 13  # inside depth of the gallery, north to south
CEILING = BASE_Y + 9
BUTTONS_Z = WALL_Z + 4  # row of buttons in front of an exhibit with views

FLOOR = "minecraft:smooth_quartz"
WALLS = "minecraft:white_concrete"
LIGHT = "minecraft:sea_lantern"

TEXT_PIXEL = 0.025  # blocks per font pixel of a text display at scale 1
YAW = {"south": 0.0, "west": 90.0, "north": 180.0, "east": -90.0}
FACING = {"north": 2, "south": 3, "west": 4, "east": 5}
STEP_OF = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}


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
        views = ex.get("views") or [{"label": "", "chart": ex["chart"]}]
        view_maps = []  # per view: {(col, row): map id}
        for view in views:
            image = render(view["chart"], WALL_W * TILE, WALL_H * TILE)
            if not view_maps:
                images.append(image)
            ids = {}
            for pos, tile in tiles(quantise(image)).items():
                blocks.maps.append(tile)
                ids[pos] = len(blocks.maps) - 1
            view_maps.append(ids)
        for (col, row), map_id in view_maps[0].items():
            frame(blocks, left + col, BASE_Y + WALL_H - row, WALL_Z + 1, map_id, tags=[f"sc_e{i}_{col}_{row}"])

        centre, room = left + WALL_W / 2, WALL_W + 2  # text may use the wall and one block either side
        text(blocks, centre, BASE_Y + WALL_H + 2.4, WALL_Z + 1.1, f"{i + 1}. {ex['question']}", 1.2, "#555555", room)
        text(blocks, centre, BASE_Y + WALL_H + 1.2, WALL_Z + 1.1, ex["answer"], 1.6, "#1d5fa8", room, bold=True)
        if ex.get("note"):
            text(blocks, centre, BASE_Y + 0.2, WALL_Z + 1.1, ex["note"], 0.6, "#777777", room)

        if len(views) > 1:
            first = math.floor(centre) - (len(views) - 1)
            for k, (view, ids) in enumerate(zip(views, view_maps)):
                bx = first + 2 * k
                command_chain(blocks, bx, BASE_Y, BUTTONS_Z, [
                    f'data modify entity @e[type=minecraft:glow_item_frame,tag=sc_e{i}_{col}_{row},limit=1] '
                    f'Item.components."minecraft:map_id" set value {map_id}'
                    for (col, row), map_id in sorted(ids.items())
                ])
                text(blocks, bx + 0.5, BASE_Y + 1.35, BUTTONS_Z + 0.55, view["label"], 0.8, "#222222", 2, bold=True)

    # the name over the entrance, on the outside of the south wall
    facade = min(x1 - 4, 30)
    text(blocks, door + 0.5, BASE_Y + 6.2, z1 + 1.05, spec["title"], 2.0, "#222222", facade, bold=True)
    if spec.get("subtitle"):
        text(blocks, door + 0.5, BASE_Y + 5.0, z1 + 1.05, spec["subtitle"], 1.0, "#555555", facade)
    # New players spawn on the highest surface at the spawn point, so spawn outside, facing the entrance.
    spawn = (door, BASE_Y, z1 + 6)
    return blocks, spawn, 180.0, images


def _chunk(x: float, z: float) -> tuple[int, int]:
    return math.floor(x) >> 4, math.floor(z) >> 4


def _uuid(*parts) -> IntArray:
    u = uuid.uuid5(uuid.NAMESPACE_URL, "schemacraft:" + ":".join(map(str, parts))).int
    return IntArray([((u >> s) & 0xFFFFFFFF) - (1 << 32 if (u >> s) & 0x80000000 else 0) for s in (96, 64, 32, 0)])


def frame(blocks: Blocks, x: int, y: int, z: int, map_id: int, facing: str = "south", tags=()) -> None:
    """Invisible glowing item frame in block (x, y, z), facing `facing`, holding a map.

    It hangs on the block behind it: facing south means it hangs on the block to the north.
    """
    dx, dz = STEP_OF[facing]
    inset = 0.5 - 0.46875  # a frame is 1/16 thick and sits against the block behind it
    px, pz = x + 0.5 - dx * (0.5 - inset), z + 0.5 - dz * (0.5 - inset)
    entity = Compound({
        "id": String("minecraft:glow_item_frame"),
        "UUID": _uuid("frame", x, y, z, facing),
        "Pos": List[Double]([Double(px), Double(y + 0.5), Double(pz)]),
        "Motion": List[Double]([Double(0), Double(0), Double(0)]),
        "Rotation": List[Float]([Float(YAW[facing]), Float(0)]),
        "TileX": Int(x), "TileY": Int(y), "TileZ": Int(z),
        "Facing": Byte(FACING[facing]),
        "Item": Compound({
            "id": String("minecraft:filled_map"), "count": Int(1),
            "components": Compound({"minecraft:map_id": Int(map_id)}),
        }),
        "ItemRotation": Byte(0), "ItemDropChance": Float(0),
        "Fixed": Byte(1), "Invisible": Byte(1), "Invulnerable": Byte(1),
    })
    if tags:
        entity["Tags"] = List[String]([String(t) for t in tags])
    blocks.mobs[_chunk(x, z)].append(entity)


def text(blocks: Blocks, x: float, y: float, z: float, text: str, scale: float, colour: str, width: float,
         bold=False, facing: str = "south", billboard: str = "fixed") -> None:
    """Floating text, fully lit, wrapped to `width` blocks.

    Fixed text stands upright and is read by someone looking against `facing`; "vertical" text
    turns to face the player, which only suits open air where it cannot swing into a wall.
    """
    s = Float(scale)
    blocks.mobs[_chunk(x, z)].append(Compound({
        "id": String("minecraft:text_display"),
        "UUID": _uuid("text", x, y, z, text),
        "Pos": List[Double]([Double(x), Double(y), Double(z)]),
        "Motion": List[Double]([Double(0), Double(0), Double(0)]),
        "Rotation": List[Float]([Float(YAW[facing]), Float(0)]),
        "text": String(json.dumps({"text": text, "color": colour, "bold": bold})),
        "billboard": String(billboard),
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


def command_chain(blocks: Blocks, x: int, y: int, z: int, commands: list[str]) -> None:
    """A button on a command block at (x, y, z); pressing it runs `commands` in order.

    The first command sits in the visible block, the rest in chain command blocks that go down
    two blocks and then run south under the ground.
    """
    blocks.set(x, y + 1, z, "minecraft:stone_button[face=floor,facing=south]")
    positions = [(x, y, z, "down"), (x, y - 1, z, "down")]
    positions += [(x, y - 2, z + k, "south") for k in range(max(0, len(commands) - 2))]
    for k, ((px, py, pz, facing), command) in enumerate(zip(positions, commands)):
        kind = "command_block" if k == 0 else "chain_command_block"
        blocks.set(px, py, pz, f"minecraft:{kind}[conditional=false,facing={facing}]")
        blocks.entities[_chunk(px, pz)].append({
            "id": f"minecraft:{kind}", "x": px, "y": py, "z": pz,
            "Command": command, "auto": k > 0, "powered": False, "conditionMet": False,
            "TrackOutput": False, "SuccessCount": 0, "UpdateLastExecution": True, "LastExecution": Long(0),
        })
