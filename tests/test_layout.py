import itertools

import pytest

from schemacraft.introspect import introspect
from schemacraft.layout import GAP, layout
from schemacraft.render import render_png


@pytest.fixture(scope="module")
def model(chinook_url):
    return introspect(chinook_url)


@pytest.fixture(scope="module")
def city(model):
    return layout(model)


def cells(b):
    return {(x, z) for x in range(b["x"], b["x"] + b["w"]) for z in range(b["z"], b["z"] + b["d"])}


def touches(cell, b):
    x, z = cell
    return any((x + dx, z + dz) in cells(b) for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)])


def test_every_table_is_a_building_inside_the_grid(model, city):
    assert {b["table"] for b in city["buildings"]} == {t["name"] for t in model["tables"]}
    w, d = city["size"]
    for b in city["buildings"]:
        assert 0 <= b["x"] and b["x"] + b["w"] <= w and 0 <= b["z"] and b["z"] + b["d"] <= d


def test_buildings_never_overlap_and_keep_a_gap(city):
    for a, b in itertools.combinations(city["buildings"], 2):
        apart_x = a["x"] + a["w"] + GAP <= b["x"] or b["x"] + b["w"] + GAP <= a["x"]
        apart_z = a["z"] + a["d"] + GAP <= b["z"] or b["z"] + b["d"] + GAP <= a["z"]
        assert apart_x or apart_z, (a["table"], b["table"])


def test_every_foreign_key_has_a_connected_road(model, city):
    buildings = {b["table"]: b for b in city["buildings"]}
    occupied = set().union(*(cells(b) for b in city["buildings"]))
    expected = {
        (t["name"], fk["ref_table"]) for t in model["tables"] for fk in t["foreign_keys"]
        if fk["ref_table"] != t["name"]
    }
    assert {(r["from"], r["to"]) for r in city["roads"]} == expected  # self-reference Employee.ReportsTo gets none

    for road in city["roads"]:
        path = [tuple(c) for c in road["cells"]]
        assert path, road
        assert not set(path) & occupied, f"road {road['from']}->{road['to']} runs through a building"
        for (x1, z1), (x2, z2) in zip(path, path[1:]):
            assert abs(x1 - x2) + abs(z1 - z2) == 1, "road has a jump"
        assert touches(path[0], buildings[road["from"]])
        assert touches(path[-1], buildings[road["to"]])


def test_height_follows_row_count(city):
    by_rows = sorted(city["buildings"], key=lambda b: b["rows"])
    assert [b["h"] for b in by_rows] == sorted(b["h"] for b in by_rows)
    assert by_rows[-1]["table"] == "PlaylistTrack"


def test_layout_is_deterministic(model, city):
    assert layout(model) == city


def test_small_groups_and_loose_tables_stay_in_town():
    """A pair of linked tables stays together; tables without foreign keys fill in compactly."""
    def table(name, refs=()):
        return {"schema": None, "name": name, "kind": "table", "row_count": 10, "columns": [{}] * 4,
                "foreign_keys": [{"ref_schema": None, "ref_table": r, "indexed": True} for r in refs]}
    chain = [table("c0")] + [table(f"c{i}", [f"c{i - 1}"]) for i in range(1, 8)]
    pair = [table("p1"), table("p2", ["p1"])]
    loose = [table(f"l{i}") for i in range(30)]
    city = layout({"tables": chain + pair + loose})

    road = next(r for r in city["roads"] if (r["from"], r["to"]) == ("p2", "p1"))
    assert len(road["cells"]) <= 2 * GAP
    built = sum(b["w"] * b["d"] for b in city["buildings"])
    w, d = city["size"]
    assert built / (w * d) > 0.2, "loose tables drifted away from the city"


def test_png_is_written(city, tmp_path):
    out = tmp_path / "city.png"
    render_png(city, str(out))
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
