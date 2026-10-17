"""Write a Sponge schematic (version 2) to paste with WorldEdit.

The schematic starts at the ground layer: paste it while standing on flat ground.
"""

from pathlib import Path

import nbtlib
import numpy as np
from nbtlib import ByteArray, Compound, Int, IntArray, List

from schemacraft.anvil import DATA_VERSION, _nbt
from schemacraft.blocks import GROUND_Y, Blocks


def write_schem(blocks: Blocks, path: Path) -> tuple[int, int, int]:
    x0, z0, x1, z1 = blocks.bounds()
    sx, sy, sz = x1 - x0 + 1, blocks.max_y - GROUND_Y + 1, z1 - z0 + 1
    base = np.zeros((sy, sz, sx), np.uint16)
    base[0] = blocks.id("minecraft:grass_block")
    arr = blocks.raster(blocks.sequence, x0, GROUND_Y, z0, sx, sy, sz, base=base)

    used, local = np.unique(arr.ravel(), return_inverse=True)  # index = x + z*W + y*W*L
    entities = []
    for chunk_entities in blocks.entities.values():
        for e in chunk_entities:
            rest = {k: v for k, v in e.items() if k not in ("id", "x", "y", "z")}
            entity = _nbt(rest)
            entity["Id"] = nbtlib.String(e["id"])
            entity["Pos"] = IntArray([e["x"] - x0, e["y"] - GROUND_Y, e["z"] - z0])
            entities.append(entity)

    schematic = Compound({
        "Version": Int(2),
        "DataVersion": Int(DATA_VERSION),
        "Width": nbtlib.Short(sx), "Height": nbtlib.Short(sy), "Length": nbtlib.Short(sz),
        "Offset": IntArray([0, 0, 0]),
        "PaletteMax": Int(len(used)),
        "Palette": Compound({blocks.states[s]: Int(i) for i, s in enumerate(used)}),
        "BlockData": ByteArray(_varints(local)),
        "BlockEntities": List[Compound](entities),
    })
    nbtlib.File(schematic, gzipped=True, root_name="Schematic").save(path)
    return sx, sy, sz


def _varints(values: np.ndarray) -> np.ndarray:
    """Encode palette indices as varints; the palette stays far below 16384 states."""
    values = values.astype(np.int64)
    big = values >= 128
    out = np.empty(len(values) + int(big.sum()), np.int64)
    pos = np.arange(len(values)) + np.concatenate(([0], np.cumsum(big)[:-1]))
    out[pos] = np.where(big, (values & 0x7F) | 0x80, values)
    out[pos[big] + 1] = values[big] >> 7
    return out.astype(np.uint8).view(np.int8)
