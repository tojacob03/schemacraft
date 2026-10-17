"""Top-down pictures of a city plan: buildings coloured by height, roads in grey."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

GROUND = (0.93, 0.92, 0.88)
ROAD = (0.55, 0.55, 0.55)
DARK_ROAD = (0.15, 0.15, 0.17)  # foreign key without an index


def _image(city: dict):
    w, d = city["size"]
    img = np.full((d, w, 3), GROUND)
    for lit in (False, True):  # lit roads win where streets are shared
        for road in city["roads"]:
            if road.get("indexed", True) == lit:
                for x, z in road["cells"]:
                    img[z, x] = ROAD if lit else DARK_ROAD

    heights = [b["h"] for b in city["buildings"]]
    norm = plt.Normalize(min(heights), max(heights) + 1e-9)
    cmap = plt.get_cmap("viridis")
    for b in city["buildings"]:
        img[b["z"]:b["z"] + b["d"], b["x"]:b["x"] + b["w"]] = cmap(norm(b["h"]))[:3]
    return img, norm, cmap


def render_png(city: dict, path: str) -> None:
    w, d = city["size"]
    img, norm, cmap = _image(city)
    scale = 0.12
    fig, ax = plt.subplots(figsize=(max(6, w * scale), max(6, d * scale)))
    ax.imshow(img, interpolation="nearest")
    for b in city["buildings"]:
        rows = "view" if b["rows"] is None else f"{b['rows']:,} rows"
        ax.text(
            b["x"] + b["w"] / 2 - 0.5, b["z"] + b["d"] / 2 - 0.5,
            f"{b['table']}\n{rows}",
            ha="center", va="center", fontsize=7, color="white" if norm(b["h"]) < 0.6 else "black",
        )
    ax.set_xlabel("x")
    ax.set_ylabel("z")
    fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=0.6, label="height (blocks)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def render_icon(city: dict, path) -> None:
    """64x64 picture for the Minecraft world list."""
    img, _, _ = _image(city)
    d, w = img.shape[:2]
    side = max(w, d)
    square = np.full((side, side, 3), GROUND)
    square[(side - d) // 2:(side - d) // 2 + d, (side - w) // 2:(side - w) // 2 + w] = img
    idx = (np.arange(64) * side / 64).astype(int)
    plt.imsave(path, square[idx][:, idx])
