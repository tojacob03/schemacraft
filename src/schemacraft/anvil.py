"""Write a playable Minecraft Java world (Anvil format of 1.21.4).

Newer Minecraft versions upgrade the world when it is opened, the same way
they upgrade any old save. Chunks are written without light (isLightOn=0),
so the game computes lighting itself.
"""

import io
import struct
import time
import zlib
from pathlib import Path

import nbtlib
import numpy as np
from nbtlib import Byte, Compound, Double, Float, Int, IntArray, List, Long, LongArray, String

from schemacraft.blocks import BASE_Y, Blocks

DATA_VERSION = 4189  # 1.21.4
VERSION_NAME = "1.21.4"
MIN_Y, HEIGHT = -64, 384
SECTIONS = HEIGHT // 16
SUPERFLAT = [("minecraft:bedrock", 1), ("minecraft:dirt", 2), ("minecraft:grass_block", 1)]


def write_world(blocks: Blocks, path: Path, name: str, spawn: tuple[int, int, int], icon=None) -> Path:
    path = Path(path)
    (path / "region").mkdir(parents=True, exist_ok=False)
    base = _ground(blocks)
    regions: dict = {}
    for cx, cz in sorted(blocks.ops):
        regions.setdefault((cx >> 5, cz >> 5), {})[(cx, cz)] = _chunk(blocks, cx, cz, base)
    for (rx, rz), chunks in regions.items():
        _write_region(path / "region" / f"r.{rx}.{rz}.mca", chunks)
    _level_dat(name, spawn).save(path / "level.dat")
    if icon is not None:
        icon(path / "icon.png")
    return path


def _ground(blocks: Blocks) -> np.ndarray:
    base = np.zeros((HEIGHT, 16, 16), np.uint16)
    y = 0
    for state, n in SUPERFLAT:
        base[y:y + n] = blocks.id(state)
        y += n
    return base


def _chunk(blocks: Blocks, cx: int, cz: int, base: np.ndarray) -> Compound:
    arr = blocks.raster(blocks.ops[(cx, cz)], cx * 16, MIN_Y, cz * 16, 16, HEIGHT, 16, base=base.copy())
    sections = []
    for sy in range(SECTIONS):
        sections.append(Compound({
            "Y": Byte(sy + MIN_Y // 16),
            "block_states": _palette_container(arr[sy * 16:(sy + 1) * 16].ravel(), blocks.states),
            "biomes": Compound({"palette": List[String]([String("minecraft:plains")])}),
        }))
    filled = arr != 0
    top = np.where(filled.any(axis=0), HEIGHT - np.argmax(filled[::-1], axis=0), 0)  # [z, x]
    heightmap = LongArray(_pack(top.ravel().astype(np.uint64), 9))
    return Compound({
        "DataVersion": Int(DATA_VERSION),
        "xPos": Int(cx), "zPos": Int(cz), "yPos": Int(MIN_Y // 16),
        "Status": String("minecraft:full"),
        "LastUpdate": Long(0), "InhabitedTime": Long(0),
        "isLightOn": Byte(0),
        "sections": List[Compound](sections),
        "block_entities": List[Compound]([_nbt(e) for e in blocks.entities.get((cx, cz), [])]),
        "Heightmaps": Compound({
            k: heightmap for k in ("MOTION_BLOCKING", "MOTION_BLOCKING_NO_LEAVES", "WORLD_SURFACE", "OCEAN_FLOOR")
        }),
        "structures": Compound({"References": Compound(), "starts": Compound()}),
        "PostProcessing": List[List]([List() for _ in range(SECTIONS)]),
        "block_ticks": List(), "fluid_ticks": List(),
    })


def _palette_container(ids: np.ndarray, states: list[str]) -> Compound:
    uniq, local = np.unique(ids, return_inverse=True)
    out = Compound({"palette": List[Compound]([_state(states[i]) for i in uniq])})
    if len(uniq) > 1:
        bits = max(4, (len(uniq) - 1).bit_length())
        out["data"] = LongArray(_pack(local.astype(np.uint64), bits))
    return out


def _pack(values: np.ndarray, bits: int) -> np.ndarray:
    """Pack values into longs, lowest bits first; an entry never spans two longs."""
    per = 64 // bits
    n = -(-len(values) // per)
    padded = np.zeros(n * per, np.uint64)
    padded[:len(values)] = values
    shifts = (np.arange(per, dtype=np.uint64) * np.uint64(bits))
    return (padded.reshape(n, per) << shifts).sum(axis=1, dtype=np.uint64).view(np.int64)


def _state(state: str) -> Compound:
    name, _, props = state.partition("[")
    out = Compound({"Name": String(name)})
    if props:
        out["Properties"] = Compound({
            k: String(v) for k, v in (p.split("=") for p in props.rstrip("]").split(","))
        })
    return out


def _nbt(value):
    if isinstance(value, bool):
        return Byte(int(value))
    if isinstance(value, int):
        return Int(value)
    if isinstance(value, str):
        return String(value)
    if isinstance(value, list):
        return List[String]([String(v) for v in value])
    return Compound({k: _nbt(v) for k, v in value.items()})


def _write_region(path: Path, chunks: dict) -> None:
    header = bytearray(8192)
    body = bytearray()
    now = int(time.time())
    for (cx, cz), chunk in chunks.items():
        buf = io.BytesIO()
        nbtlib.File(chunk).write(buf)
        data = zlib.compress(buf.getvalue())
        record = struct.pack(">IB", len(data) + 1, 2) + data
        record += b"\0" * (-len(record) % 4096)
        offset = 2 + len(body) // 4096
        i = (cx & 31) + (cz & 31) * 32
        struct.pack_into(">I", header, i * 4, (offset << 8) | (len(record) // 4096))
        struct.pack_into(">I", header, 4096 + i * 4, now)
        body += record
    path.write_bytes(bytes(header) + bytes(body))


def _level_dat(name: str, spawn: tuple[int, int, int]) -> nbtlib.File:
    x, y, z = spawn
    flat = Compound({
        "type": String("minecraft:flat"),
        "settings": Compound({
            "layers": List[Compound]([
                Compound({"block": String(b), "height": Int(n)}) for b, n in SUPERFLAT
            ]),
            "biome": String("minecraft:plains"),
            "features": Byte(0), "lakes": Byte(0),
            "structure_overrides": List[String](),
        }),
    })
    dimensions = Compound({
        "minecraft:overworld": Compound({"type": String("minecraft:overworld"), "generator": flat}),
        "minecraft:the_nether": Compound({
            "type": String("minecraft:the_nether"),
            "generator": Compound({
                "type": String("minecraft:noise"), "settings": String("minecraft:nether"),
                "biome_source": Compound({"type": String("minecraft:multi_noise"), "preset": String("minecraft:nether")}),
            }),
        }),
        "minecraft:the_end": Compound({
            "type": String("minecraft:the_end"),
            "generator": Compound({
                "type": String("minecraft:noise"), "settings": String("minecraft:end"),
                "biome_source": Compound({"type": String("minecraft:the_end")}),
            }),
        }),
    })
    rules = {
        "doDaylightCycle": "false", "doWeatherCycle": "false", "doMobSpawning": "false",
        "doTraderSpawning": "false", "doPatrolSpawning": "false", "doInsomnia": "false", "spawnRadius": "0",
    }
    data = Compound({
        "DataVersion": Int(DATA_VERSION),
        "version": Int(19133),
        "Version": Compound({
            "Id": Int(DATA_VERSION), "Name": String(VERSION_NAME), "Series": String("main"), "Snapshot": Byte(0),
        }),
        "LevelName": String(name),
        "GameType": Int(1),  # creative: fly through the city
        "allowCommands": Byte(1),
        "Difficulty": Byte(0), "DifficultyLocked": Byte(0), "hardcore": Byte(0),
        "initialized": Byte(1),
        "SpawnX": Int(x), "SpawnY": Int(y if y is not None else BASE_Y), "SpawnZ": Int(z), "SpawnAngle": Float(0),
        "Time": Long(6000), "DayTime": Long(6000), "LastPlayed": Long(int(time.time() * 1000)),
        "raining": Byte(0), "rainTime": Int(10 ** 9), "thundering": Byte(0), "thunderTime": Int(10 ** 9),
        "clearWeatherTime": Int(10 ** 9),
        "GameRules": Compound({k: String(v) for k, v in rules.items()}),
        "WorldGenSettings": Compound({
            "seed": Long(0), "generate_features": Byte(0), "bonus_chest": Byte(0), "dimensions": dimensions,
        }),
        "DataPacks": Compound({"Enabled": List[String]([String("vanilla")]), "Disabled": List[String]()}),
        "BorderCenterX": Double(0), "BorderCenterZ": Double(0), "BorderSize": Double(59999968),
        "WasModded": Byte(0),
    })
    return nbtlib.File({"Data": data}, gzipped=True)
