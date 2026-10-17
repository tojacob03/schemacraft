"""Postgres (embedded via pgserver) and DuckDB, beyond the SQLite fixtures."""

import pytest
from sqlalchemy import create_engine, text

from schemacraft.blocks import build
from schemacraft.introspect import introspect
from schemacraft.layout import layout


@pytest.fixture(scope="module")
def pg_url(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    with engine.begin() as con:
        con.execute(text("""
            CREATE SCHEMA hr;
            CREATE SCHEMA shop;
            CREATE TABLE hr.employee (id int PRIMARY KEY, manager_id int REFERENCES hr.employee(id));
            CREATE TABLE shop.customer (id int PRIMARY KEY, rep_id int REFERENCES hr.employee(id));
            CREATE INDEX ON shop.customer (rep_id);
            CREATE TABLE shop.orders (id int PRIMARY KEY, customer_id int REFERENCES shop.customer(id), note text);
            CREATE VIEW shop.big_orders AS SELECT * FROM shop.orders WHERE id > 100;
            INSERT INTO hr.employee SELECT i, NULL FROM generate_series(1, 20) i;
            INSERT INTO shop.customer SELECT i, i % 20 + 1 FROM generate_series(1, 500) i;
            INSERT INTO shop.orders
                SELECT i, i % 500 + 1, CASE WHEN i % 10 = 0 THEN 'gift' END FROM generate_series(1, 1200000) i;
        """))
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as con:
        con.execute(text("ANALYZE"))
    engine.dispose()
    yield url
    server.cleanup()


def by_key(model):
    return {f"{t['schema']}.{t['name']}": t for t in model["tables"]}


def test_postgres(pg_url):
    model = introspect(pg_url)
    tables = by_key(model)
    assert set(tables) == {"hr.employee", "shop.customer", "shop.orders", "shop.big_orders"}

    customer, orders = tables["shop.customer"], tables["shop.orders"]
    assert customer["row_count"] == 500 and "row_count_estimated" not in customer
    assert customer["foreign_keys"] == [{
        "columns": ["rep_id"], "ref_schema": "hr", "ref_table": "employee", "ref_columns": ["id"], "indexed": True,
    }]
    assert tables["hr.employee"]["foreign_keys"][0]["indexed"] is False
    assert orders["foreign_keys"][0]["indexed"] is False

    # above a million rows the planner statistics replace a full scan
    assert orders["row_count_estimated"] is True
    assert abs(orders["row_count"] - 1_200_000) < 60_000
    note = next(c for c in orders["columns"] if c["name"] == "note")
    assert abs(note["null_fraction"] - 0.9) < 0.03
    assert tables["shop.big_orders"]["kind"] == "view"


def test_postgres_schemas_become_districts(pg_url):
    model = introspect(pg_url)
    city = layout(model)
    blocks, _ = build(model, city)
    roofs = {}
    for b in city["buildings"]:
        top = -60 + b["h"] - 1
        roofs[b["schema"]] = next(
            blocks.states[op[6]] for op in blocks.sequence
            if op[1] == op[4] == top and (op[0], op[2]) == (b["x"], b["z"]) and op[3] == b["x"] + b["w"] - 1
        )
    assert len(set(roofs.values())) == 2  # one roof colour per schema


def test_duckdb(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    path = tmp_path / "shop.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE author (id INTEGER PRIMARY KEY, name VARCHAR, bio VARCHAR)")
    con.execute("CREATE TABLE book (id INTEGER PRIMARY KEY, author_id INTEGER REFERENCES author(id), title VARCHAR)")
    con.execute("CREATE TABLE review (id INTEGER PRIMARY KEY, book_id INTEGER REFERENCES book(id))")
    con.execute("CREATE INDEX ix_review_book ON review (book_id)")
    con.execute("INSERT INTO author SELECT i, 'a' || i, CASE WHEN i % 4 = 0 THEN 'x' END FROM range(40) t(i)")
    con.execute("INSERT INTO book SELECT i, i % 40, 'b' FROM range(100) t(i)")
    con.execute("CREATE VIEW long_titles AS SELECT * FROM book WHERE length(title) > 10")
    con.close()

    tables = {t["name"]: t for t in introspect(f"duckdb:///{path}")["tables"]}
    assert set(tables) == {"author", "book", "review", "long_titles"}
    assert tables["book"]["row_count"] == 100 and tables["long_titles"]["kind"] == "view"
    assert tables["book"]["foreign_keys"] == [{
        "columns": ["author_id"], "ref_schema": None, "ref_table": "author", "ref_columns": ["id"], "indexed": False,
    }]
    assert tables["review"]["foreign_keys"][0]["indexed"] is True
    bio = next(c for c in tables["author"]["columns"] if c["name"] == "bio")
    assert bio["null_fraction"] == 0.75
    assert [c["primary_key"] for c in tables["author"]["columns"]] == [True, False, False]
