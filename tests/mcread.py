"""Minimal reader for Anvil region files, written from the format spec.

Kept apart from the writer on purpose, so tests do not check the writer against itself.
"""

import io
import struct
import zlib

import nbtlib


def read_region(path) -> dict:
    raw = open(path, "rb").read()
    chunks = {}
    for i in range(1024):
        loc = struct.unpack(">I", raw[i * 4:i * 4 + 4])[0]
        if not loc >> 8:
            continue
        o = (loc >> 8) * 4096
        length, compression = struct.unpack(">IB", raw[o:o + 5])
        assert compression == 2, "zlib expected"
        nbt = nbtlib.File.parse(io.BytesIO(zlib.decompress(raw[o + 5:o + 4 + length])))
        chunks[(int(nbt["xPos"]), int(nbt["zPos"]))] = nbt
        assert (int(nbt["xPos"]) & 31) + (int(nbt["zPos"]) & 31) * 32 == i, "chunk stored at wrong slot"
    return chunks


def unpack(longs, bits: int, count: int) -> list[int]:
    per = 64 // bits
    mask = (1 << bits) - 1
    out = []
    for i in range(count):
        word = int(longs[i // per]) & 0xFFFFFFFFFFFFFFFF
        out.append((word >> ((i % per) * bits)) & mask)
    return out


def section_blocks(section) -> list[str]:
    """4096 block names of a section, index y*256 + z*16 + x."""
    states = section["block_states"]
    # 1.21.4: {Name, Properties}; Minecraft 26.x also writes bare names and {id, ...} in a mixed list
    names = [
        str(p) if isinstance(p, str) else str(p.get("Name", p.get("id", p.get(""))))
        for p in states["palette"]
    ]
    if "data" not in states:
        return [names[0]] * 4096
    bits = max(4, (len(names) - 1).bit_length())
    return [names[i] for i in unpack(states["data"], bits, 4096)]


def block_at(chunks: dict, x: int, y: int, z: int) -> str:
    chunk = chunks[(x >> 4, z >> 4)]
    for section in chunk["sections"]:
        if int(section["Y"]) == y >> 4:
            return section_blocks(section)[(y & 15) * 256 + (z & 15) * 16 + (x & 15)]
    return "minecraft:air"


def surface(chunk, min_y: int = -64) -> list[int]:
    """WORLD_SURFACE heightmap recomputed from the blocks: highest non-air block + 1, relative to min_y."""
    top = [0] * 256
    for section in sorted(chunk["sections"], key=lambda s: int(s["Y"])):
        blocks = section_blocks(section)
        base = int(section["Y"]) * 16 - min_y
        for i, name in enumerate(blocks):
            if name not in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air"):
                top[i % 256] = base + i // 256 + 1
    return top
