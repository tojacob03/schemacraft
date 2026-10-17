"""Top-down PNG of a city plan: buildings coloured by height, roads in grey."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

GROUND = (0.93, 0.92, 0.88)
ROAD = (0.55, 0.55, 0.55)


def render_png(city: dict, path: str) -> None:
    w, d = city["size"]
    img = np.full((d, w, 3), GROUND)
    for road in city["roads"]:
        for x, z in road["cells"]:
            img[z, x] = ROAD

    heights = [b["h"] for b in city["buildings"]]
    norm = plt.Normalize(min(heights), max(heights))
    cmap = plt.get_cmap("viridis")
    for b in city["buildings"]:
        img[b["z"]:b["z"] + b["d"], b["x"]:b["x"] + b["w"]] = cmap(norm(b["h"]))[:3]

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
