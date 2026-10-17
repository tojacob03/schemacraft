import pytest

from schemacraft.introspect import introspect

# Published Chinook row counts (lerocha/chinook-database v1.4.5).
ROWS = {
    "Album": 347, "Artist": 275, "Customer": 59, "Employee": 8, "Genre": 25,
    "Invoice": 412, "InvoiceLine": 2240, "MediaType": 5, "Playlist": 18,
    "PlaylistTrack": 8715, "Track": 3503,
}

FKS = {
    ("Album", "Artist"), ("Customer", "Employee"), ("Employee", "Employee"),
    ("Invoice", "Customer"), ("InvoiceLine", "Invoice"), ("InvoiceLine", "Track"),
    ("PlaylistTrack", "Playlist"), ("PlaylistTrack", "Track"), ("Track", "Album"),
    ("Track", "Genre"), ("Track", "MediaType"),
}


@pytest.fixture(scope="module")
def model(chinook_url):
    return introspect(chinook_url)


def by_name(model):
    return {t["name"]: t for t in model["tables"]}


def test_tables_and_row_counts(model):
    tables = by_name(model)
    assert {n: t["row_count"] for n, t in tables.items()} == ROWS
    assert all(t["kind"] == "table" for t in tables.values())


def test_foreign_keys(model):
    edges = {(t["name"], fk["ref_table"]) for t in model["tables"] for fk in t["foreign_keys"]}
    assert edges == FKS
    track = by_name(model)["Track"]
    album_fk = next(fk for fk in track["foreign_keys"] if fk["ref_table"] == "Album")
    assert album_fk["columns"] == ["AlbumId"] and album_fk["ref_columns"] == ["AlbumId"]


def test_primary_keys_and_composite_pk(model):
    pt = {c["name"]: c for c in by_name(model)["PlaylistTrack"]["columns"]}
    assert pt["PlaylistId"]["primary_key"] and pt["TrackId"]["primary_key"]


def test_null_fractions(model):
    emp = {c["name"]: c for c in by_name(model)["Employee"]["columns"]}
    assert emp["ReportsTo"]["null_fraction"] == 0.125  # only the general manager has no boss
    assert emp["EmployeeId"]["null_fraction"] == 0.0


def test_foreign_key_index_detection(model, library_url):
    assert all(fk["indexed"] for t in model["tables"] for fk in t["foreign_keys"])  # Chinook indexes every FK
    library = by_name(introspect(library_url))
    assert library["book"]["foreign_keys"][0]["indexed"] is False
    assert library["review"]["foreign_keys"][0]["indexed"] is True


def test_views(library_url):
    view = by_name(introspect(library_url))["top_books"]
    assert view["kind"] == "view" and view["row_count"] is None
    assert [c["name"] for c in view["columns"]] == ["book_id", "stars"]


def test_indexes_present(model):
    track_ix = {tuple(ix["columns"]) for ix in by_name(model)["Track"]["indexes"]}
    assert ("AlbumId",) in track_ix
