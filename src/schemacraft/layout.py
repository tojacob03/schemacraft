"""Turn the database model into a city plan on an integer grid (x, z).

Footprint grows with column count, height with log10(row count).
Tables linked by foreign keys sit close together and get a road.
"""

import math

import networkx as nx

GAP = 4  # minimum free cells between two buildings
MARGIN = 4  # free border around the city
ROAD_REUSE = 0.4  # cost of walking an existing road: roads merge into streets


def key(t: dict) -> str:
    return f"{t['schema']}.{t['name']}" if t["schema"] else t["name"]


def footprint(n_columns: int) -> int:
    return 5 + 2 * math.ceil(math.sqrt(n_columns))


def height(rows: int | None) -> int:
    return 4 + round(12 * math.log10(rows + 1)) if rows else 4


def layout(model: dict, seed: int = 42) -> dict:
    tables = {key(t): t for t in model["tables"]}
    graph = nx.Graph()
    graph.add_nodes_from(tables)
    links = set()
    for k, t in tables.items():
        for fk in t["foreign_keys"]:
            ref = key({"schema": fk["ref_schema"], "name": fk["ref_table"]})
            if ref != k and ref in tables:
                graph.add_edge(k, ref)
                links.add((k, ref))

    sizes = {k: footprint(len(t["columns"])) for k, t in tables.items()}
    spread = math.sqrt(sum((s + GAP) ** 2 for s in sizes.values()))
    pos = nx.spring_layout(graph, seed=seed)
    rects = _place(
        {k: (round(pos[k][0] * spread - sizes[k] / 2), round(pos[k][1] * spread - sizes[k] / 2)) for k in tables},
        sizes,
    )

    min_x = min(r[0] for r in rects.values())
    min_z = min(r[1] for r in rects.values())
    for r in rects.values():
        r[0] += MARGIN - min_x
        r[1] += MARGIN - min_z
    size = [
        max(r[0] + r[2] for r in rects.values()) + MARGIN,
        max(r[1] + r[3] for r in rects.values()) + MARGIN,
    ]

    buildings = [
        {
            "table": k,
            "x": r[0], "z": r[1], "w": r[2], "d": r[3],
            "h": height(tables[k]["row_count"]),
            "rows": tables[k]["row_count"],
            "columns": len(tables[k]["columns"]),
        }
        for k, r in rects.items()
    ]
    return {"size": size, "buildings": buildings, "roads": _roads(rects, sorted(links), size)}


def _place(targets: dict, sizes: dict) -> dict:
    """Put each building at its target, or the nearest spot keeping GAP to all placed ones.

    Buildings closest to the centre go first, so the core stays dense.
    """
    cx = sum(x for x, _ in targets.values()) / len(targets)
    cz = sum(z for _, z in targets.values()) / len(targets)
    order = sorted(targets, key=lambda k: ((targets[k][0] - cx) ** 2 + (targets[k][1] - cz) ** 2, k))
    placed: dict = {}
    for k in order:
        tx, tz = targets[k]
        s = sizes[k]
        r = 0
        while True:
            ring = [(dx, dz) for dx in range(-r, r + 1) for dz in range(-r, r + 1) if max(abs(dx), abs(dz)) == r]
            ring.sort(key=lambda o: (o[0] ** 2 + o[1] ** 2, o))
            spot = next((o for o in ring if _fits((tx + o[0], tz + o[1], s, s), placed.values())), None)
            if spot:
                placed[k] = [tx + spot[0], tz + spot[1], s, s]
                break
            r += 1
    return {k: placed[k] for k in sorted(placed)}


def _fits(rect, others) -> bool:
    x, z, w, d = rect
    return all(
        x + w + GAP <= ox or ox + ow + GAP <= x or z + d + GAP <= oz or oz + od + GAP <= z
        for ox, oz, ow, od in others
    )


def _roads(rects: dict, links: list, size: list) -> list:
    blocked = {
        (x, z)
        for x0, z0, w, d in rects.values()
        for x in range(x0, x0 + w)
        for z in range(z0, z0 + d)
    }
    grid = nx.grid_2d_graph(*size)
    grid.remove_nodes_from(blocked)
    road_cells: set = set()

    def cost(u, v, _):
        if isinstance(u, str) or isinstance(v, str):
            return 0
        return ROAD_REUSE if v in road_cells else 1

    roads = []
    for a, b in links:
        grid.add_edges_from(("S", c) for c in _perimeter(rects[a]) if c in grid)
        grid.add_edges_from((c, "T") for c in _perimeter(rects[b]) if c in grid)
        path = nx.dijkstra_path(grid, "S", "T", weight=cost)[1:-1]
        grid.remove_nodes_from(["S", "T"])
        road_cells.update(path)
        roads.append({"from": a, "to": b, "cells": [list(c) for c in path]})
    return roads


def _perimeter(rect) -> list:
    x0, z0, w, d = rect
    return (
        [(x, z0 - 1) for x in range(x0, x0 + w)]
        + [(x, z0 + d) for x in range(x0, x0 + w)]
        + [(x0 - 1, z) for z in range(z0, z0 + d)]
        + [(x0 + w, z) for z in range(z0, z0 + d)]
    )
