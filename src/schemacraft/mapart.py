"""Pictures on Minecraft maps: quantise an RGB image to map colours and cut it into 128x128 tiles."""

import numpy as np

# Map base colours 1-61 (0 is transparent), from https://minecraft.wiki/w/Map_item_format
BASE = [
    (127, 178, 56), (247, 233, 163), (199, 199, 199), (255, 0, 0), (160, 160, 255), (167, 167, 167),
    (0, 124, 0), (255, 255, 255), (164, 168, 184), (151, 109, 77), (112, 112, 112), (64, 64, 255),
    (143, 119, 72), (255, 252, 245), (216, 127, 51), (178, 76, 216), (102, 153, 216), (229, 229, 51),
    (127, 204, 25), (242, 127, 165), (76, 76, 76), (153, 153, 153), (76, 127, 153), (127, 63, 178),
    (51, 76, 178), (102, 76, 51), (102, 127, 51), (153, 51, 51), (25, 25, 25), (250, 238, 77),
    (92, 219, 213), (74, 128, 255), (0, 217, 58), (129, 86, 49), (112, 2, 0), (209, 177, 161),
    (159, 82, 36), (149, 87, 108), (112, 108, 138), (186, 133, 36), (103, 117, 53), (160, 77, 78),
    (57, 41, 35), (135, 107, 98), (87, 92, 92), (122, 73, 88), (76, 62, 92), (76, 50, 35),
    (76, 82, 42), (142, 60, 46), (37, 22, 16), (189, 48, 49), (148, 63, 97), (92, 25, 29),
    (22, 126, 134), (58, 142, 140), (86, 44, 62), (20, 180, 133), (100, 100, 100), (216, 175, 147),
    (127, 167, 150),
]
SHADES = (180, 220, 255, 135)  # colour byte = base id * 4 + shade index

TILE = 128


def palette() -> tuple[np.ndarray, np.ndarray]:
    """Every opaque map colour as RGB, with its colour byte."""
    rgb, codes = [], []
    for base, (r, g, b) in enumerate(BASE, start=1):
        for shade, m in enumerate(SHADES):
            rgb.append((r * m // 255, g * m // 255, b * m // 255))
            codes.append(base * 4 + shade)
    return np.array(rgb, np.int32), np.array(codes, np.uint8)


def colour(r: int, g: int, b: int) -> tuple[int, int, int]:
    """The map colour closest to an RGB value, as RGB: draw with these and nothing gets muddied."""
    rgb, _ = palette()
    return tuple(int(v) for v in rgb[np.argmin(((rgb - (r, g, b)) ** 2).sum(axis=1))])


def quantise(image: np.ndarray) -> np.ndarray:
    """RGB image (H, W, 3, uint8) -> map colour bytes (H, W), nearest colour by RGB distance."""
    rgb, codes = palette()
    flat = image.reshape(-1, 3).astype(np.int32)
    out = np.empty(len(flat), np.uint8)
    for start in range(0, len(flat), 65536):  # keep the distance matrix small
        chunk = flat[start:start + 65536]
        d = ((chunk[:, None, :] - rgb[None, :, :]) ** 2).sum(axis=2)
        out[start:start + 65536] = codes[d.argmin(axis=1)]
    return out.reshape(image.shape[:2])


def to_rgb(codes: np.ndarray) -> np.ndarray:
    """Map colour bytes back to RGB, for previews."""
    rgb, palette_codes = palette()
    lut = np.zeros((256, 3), np.uint8)
    lut[palette_codes] = rgb
    return lut[codes]


def tiles(codes: np.ndarray) -> dict:
    """Cut map colours into 128x128 tiles: {(column, row): tile}, row 0 at the top."""
    h, w = codes.shape
    assert h % TILE == 0 and w % TILE == 0, "image size must be a multiple of 128"
    return {
        (c, r): codes[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE]
        for r in range(h // TILE) for c in range(w // TILE)
    }
