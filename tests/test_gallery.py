"""Gallery worlds: map walls, item frames and text displays, read back from the written files."""

import io
import json
import math
import struct
import zlib

import nbtlib
import numpy as np
import pytest

from schemacraft.anvil import DATA_VERSION, write_world
from schemacraft.blocks import BASE_Y
from schemacraft.charts import render
from schemacraft.gallery import DEPTH, STEP, WALL_H, WALL_W, WALL_Z, build_gallery
from schemacraft.mapart import palette, quantise, tiles, to_rgb

TEXT_PIXEL = 0.025  # blocks per font pixel of a text display at scale 1 (as in Minecraft's renderer)

SPEC = {
    "title": "Test gallery",
    "subtitle": "two walls",
    "exhibits": [
        {"question": "Which cards?", "answer": "Fireball, mostly", "note": "n = 356",
         "chart": {"type": "bars", "max": 100, "ref": {"value": 50, "label": "average"},
                   "panels": [{"title": "Game 1", "bars": [{"label": "Fireball", "value": 39.3, "text": "39,3 %"},
                                                           {"label": "Zap", "value": 12, "text": "12,0 %", "highlight": True}]}]}},
        {"question": "Which decks?", "answer": "Hog cycle",
         "chart": {"type": "table", "columns": ["Deck", "Games", "Win"], "widths": [0.6, 0.2, 0.2], "bars": [2], "max": 100,
                   "rows": [["Hog, Musketeer, Ice Golem, Skeletons, Ice Spirit, Cannon, Fireball, Log", "154", "73,4 %"]]}},
    ],
}


def test_palette_has_every_opaque_map_colour():
    rgb, codes = palette()
    assert len(codes) == 61 * 4 and codes.min() == 4 and codes.max() == 247
    assert tuple(rgb[list(codes).index(8 * 4 + 2)]) == (255, 255, 255)  # SNOW, unshaded
    assert tuple(rgb[list(codes).index(1 * 4 + 0)]) == (127 * 180 // 255, 178 * 180 // 255, 56 * 180 // 255)


def test_charts_survive_the_map_palette_unchanged():
    for ex in SPEC["exhibits"]:
        image = render(ex["chart"], 768, 512)
        assert image.shape == (512, 768, 3)
        assert (to_rgb(quantise(image)) == image).all(), "chart uses a colour maps cannot show"
        assert len(np.unique(image.reshape(-1, 3), axis=0)) > 2


def test_tiles_are_cut_row_by_row_from_the_top():
    codes = np.zeros((256, 384), np.uint8)
    codes[0, 128] = 7  # top row, second column
    codes[255, 0] = 9  # bottom row, first column
    t = tiles(codes)
    assert set(t) == {(c, r) for c in range(3) for r in range(2)}
    assert t[(1, 0)][0, 0] == 7 and t[(0, 1)][127, 0] == 9


def read_entities(world):
    out = []
    for region in (world / "entities").glob("*.mca"):
        raw = region.read_bytes()
        for i in range(1024):
            loc = struct.unpack(">I", raw[i * 4:i * 4 + 4])[0]
            if loc >> 8:
                o = (loc >> 8) * 4096
                length = struct.unpack(">I", raw[o:o + 4])[0]
                chunk = nbtlib.File.parse(io.BytesIO(zlib.decompress(raw[o + 5:o + 4 + length])))
                # same container Minecraft 26.3 writes: Position, DataVersion, Entities
                assert set(chunk) == {"DataVersion", "Position", "Entities"}
                assert chunk["DataVersion"] == DATA_VERSION
                for e in chunk["Entities"]:
                    assert (math.floor(e["Pos"][0]) >> 4, math.floor(e["Pos"][2]) >> 4) == tuple(int(v) for v in chunk["Position"])
                    out.append(e)
    return out


@pytest.fixture(scope="module")
def gallery(tmp_path_factory):
    blocks, spawn, angle, images = build_gallery(SPEC)
    world = write_world(blocks, tmp_path_factory.mktemp("g") / "world", "Test", spawn, angle=angle)
    return world, images, spawn, blocks


def test_every_tile_hangs_in_a_frame_and_shows_the_chart(gallery):
    world, images, _, _ = gallery
    frames = [e for e in read_entities(world) if e["id"] == "minecraft:glow_item_frame"]
    assert len(frames) == len(images) * WALL_W * WALL_H
    maps = {int(f["Item"]["components"]["minecraft:map_id"]): f for f in frames}
    assert len(maps) == len(frames)  # one map per frame

    for f in frames:
        assert f["Facing"] == 3 and f["Fixed"] == 1 and f["Invisible"] == 1
        assert (int(f["TileX"]), int(f["TileY"]), int(f["TileZ"])) == tuple(math.floor(v) for v in f["Pos"])

    # put the first wall back together from the map files, using the frame positions
    first = sorted((f for f in frames if int(f["TileX"]) < 3 + WALL_W), key=lambda f: (-int(f["TileY"]), int(f["TileX"])))
    wall = np.zeros((WALL_H * 128, WALL_W * 128), np.uint8)
    for f in first:
        data = nbtlib.load(world / "data" / f"map_{int(f['Item']['components']['minecraft:map_id'])}.dat")
        assert data["DataVersion"] == DATA_VERSION and data["data"]["locked"] == 1
        tile = np.array(data["data"]["colors"], np.int8).view(np.uint8).reshape(128, 128)
        col, row = int(f["TileX"]) - 3, BASE_Y + WALL_H - int(f["TileY"])
        wall[row * 128:(row + 1) * 128, col * 128:(col + 1) * 128] = tile
    assert (wall == quantise(images[0])).all()

    counts = nbtlib.load(world / "data" / "idcounts.dat")
    assert counts["data"]["map"] == len(frames) - 1


def test_questions_and_answers_float_above_the_walls(gallery):
    world, _, _, _ = gallery
    texts = [json.loads(str(e["text"]))["text"] for e in read_entities(world) if e["id"] == "minecraft:text_display"]
    for i, ex in enumerate(SPEC["exhibits"], start=1):
        assert f"{i}. {ex['question']}" in texts and ex["answer"] in texts
    assert "Test gallery" in texts and "n = 356" in texts


def test_spawn_looks_at_the_first_wall(gallery):
    world, _, spawn, _ = gallery
    data = nbtlib.load(world / "level.dat")["Data"]
    assert float(data["SpawnAngle"]) == 180.0  # north, where the walls hang
    assert (data["SpawnX"], data["SpawnZ"]) == (spawn[0], spawn[2])


def test_text_never_reaches_through_a_wall(gallery):
    world, _, _, _ = gallery
    x1, z1 = 2 + STEP * len(SPEC["exhibits"]) + 1, WALL_Z + DEPTH
    for e in read_entities(world):
        if e["id"] != "minecraft:text_display":
            continue
        assert e["billboard"] == "fixed", "a turning text swings into the walls"
        text = json.loads(str(e["text"]))["text"]
        scale = float(e["transformation"]["scale"][0])
        widest = min(int(e["line_width"]), len(text) * 7)  # 7 px: the widest bold glyphs of the Minecraft font
        half = widest * TEXT_PIXEL * scale / 2
        x, z = float(e["Pos"][0]), float(e["Pos"][2])
        assert 1 <= x - half and x + half <= x1, f"{text!r} is wider than the gallery"
        if z < z1:  # inside: stays within its own wall and the gap next to it
            assert half <= (WALL_W + 2) / 2, f"{text!r} runs into the next wall"


def test_spawn_is_outside_in_front_of_an_open_door(gallery):
    _, _, (x, y, z), blocks = gallery
    z1 = WALL_Z + DEPTH
    assert z > z1, "players spawn on the highest surface: inside the gallery that is the roof"
    door = blocks.raster(blocks.sequence, x, y, z1, 1, 4, 1)
    assert (door == 0).all(), "the entrance in front of the spawn is closed"


def test_buttons_switch_every_frame_to_the_maps_of_their_view(tmp_path):
    bars = lambda v: {"type": "bars", "panels": [{"title": f"view {v}", "bars": [{"label": "a", "value": v}]}]}  # noqa: E731
    spec = {"title": "t", "exhibits": [{"question": "q", "answer": "a",
                                        "views": [{"label": f"V{v}", "chart": bars(v)} for v in (1, 2, 3)]}]}
    blocks, spawn, angle, _ = build_gallery(spec)
    world = write_world(blocks, tmp_path / "w", "t", spawn, angle=angle)
    assert len(blocks.maps) == 3 * WALL_W * WALL_H

    frames = {str(f["Tags"][0]): f for f in read_entities(world) if f["id"] == "minecraft:glow_item_frame"}
    commands = {}  # (x, y, z) -> command block
    for c in blocks.entities.values():
        for e in c:
            if "Command" in e:
                commands[(e["x"], e["y"], e["z"])] = e
    starts = [p for p, e in commands.items() if not e["auto"]]
    assert len(starts) == 3  # one button per view

    for k, (x, y, z) in enumerate(sorted(starts)):
        # follow the chain: down, down, then south under the ground
        chain, pos = [], (x, y, z)
        while pos in commands:
            chain.append(commands[pos]["Command"])
            px, py, pz = pos
            pos = (px, py - 1, pz) if py > y - 2 else (px, py, pz + 1)
        assert len(chain) == len(frames), "the chain must reach every frame"
        for command in chain:
            tag = command.split("tag=")[1].split(",")[0]
            map_id = int(command.rsplit(" ", 1)[1])
            assert tag in frames
            assert map_id // (WALL_W * WALL_H) == k, "a button shows the maps of its own view"


def test_walls_stay_closed_except_the_entrance_and_the_room_is_lit():
    blocks, (sx, _, _), _, _ = build_gallery(SPEC)
    x1, z1 = 2 + STEP * len(SPEC["exhibits"]) + 1, WALL_Z + DEPTH
    south = blocks.raster(blocks.sequence, 0, BASE_Y, z1, x1 + 1, 4, 1)[:, 0, :]  # [y, x]
    names = np.vectorize(lambda i: blocks.states[i])(south)
    openings = sorted({x for y, x in zip(*np.nonzero(names != "minecraft:white_concrete"))})
    assert openings == [sx - 1, sx, sx + 1], "only the entrance may be open"
    inside = blocks.raster(blocks.sequence, 1, BASE_Y + 3, WALL_Z + 1, x1 - 1, 1, DEPTH - 1)
    assert (np.vectorize(lambda i: blocks.states[i].startswith("minecraft:light"))(inside)).sum() >= len(SPEC["exhibits"]) * 2
