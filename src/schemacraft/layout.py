"""Turn the database model into a city plan on an integer grid (x, z).

Footprint grows with column count, height with log10(row count).
Tables linked by foreign keys sit close together and get a road;
tables of the same schema form a district.
"""

import heapq
import math
from collections import defaultdict

import networkx as nx

GAP = 4  # minimum free cells between two buildings
MARGIN = 4  # free border around the city
ROAD_REUSE = 0.4  # cost of walking an existing road: roads merge into streets
BUCKET = 32  # cell size of the spatial index used while placing buildings


def key(t: dict) -> str:
    return f"{t['schema']}.{t['name']}" if t["schema"] else t["name"]


def footprint(n_columns: int) -> int:
    return 5 + 2 * math.ceil(math.sqrt(n_columns))


def height(rows: int | None) -> int:
    return 4 + round(12 * math.log10(rows + 1)) if rows else 4


def layout(model: dict, seed: int = 42) -> dict:
    tables = {key(t): t for t in model["tables"]}
    fk_graph = nx.Graph()
    fk_graph.add_nodes_from(tables)
    links: dict = {}  # (from, to) -> every foreign key between them is indexed
    for k, t in tables.items():
        for fk in t["foreign_keys"]:
            ref = key({"schema": fk["ref_schema"], "name": fk["ref_table"]})
            if ref != k and ref in tables:
                fk_graph.add_edge(k, ref, weight=1.0)
                links[(k, ref)] = links.get((k, ref), True) and fk.get("indexed", True)
    sizes = {k: footprint(len(t["columns"])) for k, t in tables.items()}

    # The biggest web of linked tables gets a force-directed layout. Smaller groups and
    # tables without foreign keys would drift into an outer ring there, so they dock
    # onto the edge of their schema's district afterwards, member next to member.
    groups = sorted(nx.connected_components(fk_graph), key=lambda c: (-len(c), min(c)))
    core = groups[0] if len(groups[0]) > 1 else set()
    graph = fk_graph.subgraph(core).copy()
    if len({tables[k]["schema"] for k in core}) > 1:  # an invisible hub per schema pulls its tables together
        for k in core:
            graph.add_edge(("hub", tables[k]["schema"]), k, weight=0.3)
    spread = math.sqrt(sum((sizes[k] + GAP) ** 2 for k in core))
    pos = nx.spring_layout(graph, seed=seed) if core else {}
    targets = {k: (round(pos[k][0] * spread - sizes[k] / 2), round(pos[k][1] * spread - sizes[k] / 2)) for k in core}

    def centre(points):
        points = list(points)
        if not points:
            return 0, 0
        return round(sum(x for x, _ in points) / len(points)), round(sum(z for _, z in points) / len(points))

    districts = {s: centre(targets[k] for k in core if tables[k]["schema"] == s) for s in {t["schema"] for t in tables.values()}}
    fallback = centre(targets.values())
    follow = {}  # table -> already placed neighbour it docks onto, or None for the group's first table
    for group in groups:
        if group is core:
            continue
        first = min(group)
        follow[first] = None
        for parent, child in nx.bfs_edges(fk_graph.subgraph(group), first):
            follow[child] = parent

    def target(k, placed):
        if k in targets:
            return targets[k]
        if follow[k] is None:
            s = tables[k]["schema"]
            return districts[s] if any(tables[c]["schema"] == s for c in core) else fallback
        return tuple(placed[follow[k]][:2])

    centre_x, centre_z = fallback
    order = sorted(core, key=lambda k: ((targets[k][0] - centre_x) ** 2 + (targets[k][1] - centre_z) ** 2, k))
    order += list(follow)
    rects = _place(order, target, sizes)

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
            "schema": tables[k]["schema"],
            "kind": tables[k]["kind"],
            "x": r[0], "z": r[1], "w": r[2], "d": r[3],
            "h": height(tables[k]["row_count"]),
            "rows": tables[k]["row_count"],
            "columns": len(tables[k]["columns"]),
        }
        for k, r in rects.items()
    ]
    return {"size": size, "buildings": buildings, "roads": _roads(rects, links, size)}


def _place(order: list, target, sizes: dict) -> dict:
    """Put each building, in order, at target(k, placed) or the nearest spot keeping GAP to all placed ones."""
    index: dict = defaultdict(list)  # bucket -> placed rects inflated by GAP
    placed: dict = {}
    reached: dict = {}  # target -> ring radius where the last search there succeeded
    for k in order:
        tx, tz = target(k, placed)
        s = sizes[k]
        r = reached.get((tx, tz), 0)  # many groups start at the same district centre: skip the rings already full
        while True:
            spot = next((o for o in _ring(r) if _fits(tx + o[0], tz + o[1], s, index)), None)
            if spot:
                rect = [tx + spot[0], tz + spot[1], s, s]
                placed[k] = rect
                reached[(tx, tz)] = r
                grown = (rect[0] - GAP, rect[1] - GAP, s + 2 * GAP, s + 2 * GAP)
                for b in _buckets(*grown):
                    index[b].append(grown)
                break
            r += 1
    return {k: placed[k] for k in sorted(placed)}


def _ring(r: int) -> list:
    if r == 0:
        return [(0, 0)]
    cells = [(d, -r) for d in range(-r, r + 1)] + [(d, r) for d in range(-r, r + 1)]
    cells += [(-r, d) for d in range(-r + 1, r)] + [(r, d) for d in range(-r + 1, r)]
    return sorted(cells, key=lambda o: (o[0] ** 2 + o[1] ** 2, o))


def _buckets(x, z, w, d):
    for bx in range(x // BUCKET, (x + w - 1) // BUCKET + 1):
        for bz in range(z // BUCKET, (z + d - 1) // BUCKET + 1):
            yield bx, bz


def _fits(x, z, s, index) -> bool:
    for b in _buckets(x, z, s, s):
        for ox, oz, ow, od in index.get(b, ()):
            if x < ox + ow and ox < x + s and z < oz + od and oz < z + s:
                return False
    return True


def _roads(rects: dict, links: dict, size: list) -> list:
    blocked = {
        (x, z)
        for x0, z0, w, d in rects.values()
        for x in range(x0, x0 + w)
        for z in range(z0, z0 + d)
    }
    road_cells: set = set()
    roads = []
    for (a, b), indexed in sorted(links.items()):
        path = _route(rects[a], rects[b], blocked, road_cells, size)
        road_cells.update(path)
        roads.append({"from": a, "to": b, "indexed": indexed, "cells": [list(c) for c in path]})
    return roads


def _route(ra, rb, blocked, road_cells, size) -> list:
    """A* from any free cell next to building a to any free cell next to building b."""
    w, d = size

    def free(c):
        return 0 <= c[0] < w and 0 <= c[1] < d and c not in blocked

    goal = {c for c in _perimeter(rb) if free(c)}
    gx0, gz0 = rb[0] - 1, rb[1] - 1
    gx1, gz1 = rb[0] + rb[2], rb[1] + rb[3]

    def h(x, z):
        return (max(gx0 - x, 0, x - gx1) + max(gz0 - z, 0, z - gz1)) * ROAD_REUSE

    g = {c: 0.0 for c in _perimeter(ra) if free(c)}
    parent: dict = {}
    heap = [(h(*c), 0.0, c) for c in sorted(g)]
    heapq.heapify(heap)
    while heap:
        _, cost, c = heapq.heappop(heap)
        if cost > g[c]:
            continue
        if c in goal:
            path = [c]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            return path[::-1]
        x, z = c
        for n in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
            if not free(n):
                continue
            step = cost + (ROAD_REUSE if n in road_cells else 1.0)
            if step < g.get(n, math.inf):
                g[n] = step
                parent[n] = c
                heapq.heappush(heap, (step + h(*n), step, n))
    raise RuntimeError("no route between buildings")


def _perimeter(rect) -> list:
    x0, z0, w, d = rect
    return (
        [(x, z0 - 1) for x in range(x0, x0 + w)]
        + [(x, z0 + d) for x in range(x0, x0 + w)]
        + [(x0 - 1, z) for z in range(z0, z0 + d)]
        + [(x0 + w, z) for z in range(z0, z0 + d)]
    )
