"""Read a database's structure and basic statistics into a plain JSON model.

The model knows nothing about Minecraft; layout and export build on it.
"""

from collections import defaultdict

from sqlalchemy import create_engine, func, inspect, make_url, select, text
from sqlalchemy.sql import column, table

ESTIMATE_ABOVE = 1_000_000  # Postgres: trust the planner statistics instead of scanning bigger tables


def introspect(url: str) -> dict:
    if url.startswith("duckdb:"):
        return _introspect_duckdb(url)
    engine = create_engine(url)
    insp = inspect(engine)
    tables = []
    with engine.connect() as conn:
        for schema in _schemas(insp):
            for name in insp.get_table_names(schema=schema):
                tables.append(_table(insp, conn, schema, name, "table"))
            for name in insp.get_view_names(schema=schema):
                tables.append(_table(insp, conn, schema, name, "view"))
    engine.dispose()
    return {"dialect": engine.dialect.name, "tables": tables}


def _schemas(insp) -> list[str | None]:
    """Every user schema on Postgres; elsewhere just the default one (MySQL lists other databases)."""
    if insp.dialect.name != "postgresql":
        return [None]
    return [s for s in insp.get_schema_names() if s != "information_schema" and not s.startswith("pg_")]


def _table(insp, conn, schema, name, kind) -> dict:
    pk_columns = insp.get_pk_constraint(name, schema=schema)["constrained_columns"]
    pk = set(pk_columns)
    indexes = [
        {"name": ix["name"], "columns": ix["column_names"], "unique": bool(ix["unique"])}
        for ix in insp.get_indexes(name, schema=schema)
    ]
    leading = [pk_columns] + [ix["columns"] for ix in indexes]
    columns = [
        {
            "name": c["name"],
            "type": str(c["type"]),
            "nullable": c["nullable"],
            "primary_key": c["name"] in pk,
        }
        for c in insp.get_columns(name, schema=schema)
    ]
    entry = {
        "schema": schema,
        "name": name,
        "kind": kind,
        "row_count": None,
        "columns": columns,
        "foreign_keys": [
            {
                "columns": fk["constrained_columns"],
                "ref_schema": fk["referred_schema"],
                "ref_table": fk["referred_table"],
                "ref_columns": fk["referred_columns"],
                # a lookup by these columns can use an index: they lead the primary key or an index
                "indexed": any(
                    cols[: len(fk["constrained_columns"])] == fk["constrained_columns"] for cols in leading
                ),
            }
            for fk in insp.get_foreign_keys(name, schema=schema)
        ],
        "indexes": indexes,
    }
    if kind == "table":
        if conn.dialect.name != "postgresql" or not _add_pg_estimates(conn, schema, entry):
            _add_counts(conn, schema, entry)
    return entry


def _add_pg_estimates(conn, schema, entry) -> bool:
    """Row estimate and null fractions from the planner statistics, for big tables only."""
    rows = conn.execute(
        text("SELECT c.reltuples::bigint FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
             "WHERE n.nspname = :s AND c.relname = :t"),
        {"s": schema, "t": entry["name"]},
    ).scalar()
    if rows is None or rows < ESTIMATE_ABOVE:
        return False
    null_frac = dict(conn.execute(
        text("SELECT attname, null_frac FROM pg_stats WHERE schemaname = :s AND tablename = :t"),
        {"s": schema, "t": entry["name"]},
    ).all())
    entry["row_count"] = rows
    entry["row_count_estimated"] = True
    for col in entry["columns"]:
        col["null_fraction"] = round(float(null_frac.get(col["name"], 0.0)), 4)
    return True


def _introspect_duckdb(url: str) -> dict:
    """DuckDB through its own catalog functions; duckdb-engine's reflection breaks on SQLAlchemy 2.1."""
    import duckdb

    con = duckdb.connect(make_url(url).database or ":memory:", read_only=True)
    db = con.sql("SELECT current_database()").fetchone()[0]

    def rows(sql):
        return con.execute(sql, [db]).fetchall()

    def q(name):
        return '"' + name.replace('"', '""') + '"'

    columns = defaultdict(list)
    for s, t, c, typ, nullable in rows(
        "SELECT schema_name, table_name, column_name, data_type, is_nullable FROM duckdb_columns() "
        "WHERE database_name = ? ORDER BY schema_name, table_name, column_index"
    ):
        columns[(s, t)].append({"name": c, "type": typ, "nullable": nullable, "primary_key": False})
    pks, fks, indexes = defaultdict(list), defaultdict(list), defaultdict(list)
    for s, t, kind, cols, ref, ref_cols in rows(
        "SELECT schema_name, table_name, constraint_type, constraint_column_names, referenced_table, "
        "referenced_column_names FROM duckdb_constraints() WHERE database_name = ? "
        "AND constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')"
    ):
        if kind == "PRIMARY KEY":
            pks[(s, t)] = cols
        else:  # DuckDB names only the referenced table, which lives in the same schema
            fks[(s, t)].append({"columns": cols, "ref_schema": s, "ref_table": ref, "ref_columns": ref_cols})
    for s, t, name, unique, expr in rows(
        "SELECT schema_name, table_name, index_name, is_unique, expressions FROM duckdb_indexes() WHERE database_name = ?"
    ):
        cols = [c.strip().strip('"') for c in expr.strip("[]").split(",")]
        indexes[(s, t)].append({"name": name, "columns": cols, "unique": unique})

    objects = rows("SELECT schema_name, table_name, 'table' FROM duckdb_tables() WHERE database_name = ? AND NOT internal")
    objects += rows("SELECT schema_name, view_name, 'view' FROM duckdb_views() WHERE database_name = ? AND NOT internal")
    multi = len({s for s, _, _ in objects}) > 1
    tables = []
    for s, t, kind in sorted(objects):
        cols = columns[(s, t)]
        for c in cols:
            c["primary_key"] = c["name"] in pks[(s, t)]
        leading = [pks[(s, t)]] + [ix["columns"] for ix in indexes[(s, t)]]
        entry = {
            "schema": s if multi else None,
            "name": t,
            "kind": kind,
            "row_count": None,
            "columns": cols,
            "foreign_keys": [
                {**fk, "ref_schema": fk["ref_schema"] if multi else None,
                 "indexed": any(lead[: len(fk["columns"])] == fk["columns"] for lead in leading)}
                for fk in fks[(s, t)]
            ],
            "indexes": indexes[(s, t)],
        }
        if kind == "table":
            counts = con.execute(
                f"SELECT count(*), {', '.join(f'count({q(c["name"])})' for c in cols)} FROM {q(s)}.{q(t)}"
            ).fetchone()
            entry["row_count"] = counts[0]
            for c, non_null in zip(cols, counts[1:]):
                c["null_fraction"] = round(1 - non_null / counts[0], 4) if counts[0] else 0.0
        tables.append(entry)
    con.close()
    return {"dialect": "duckdb", "tables": tables}


def _add_counts(conn, schema, entry) -> None:
    """Exact row count and per-column null fraction in a single scan."""
    names = [c["name"] for c in entry["columns"]]
    t = table(entry["name"], *[column(n) for n in names], schema=schema)
    row = conn.execute(select(func.count(), *[func.count(t.c[n]) for n in names])).one()
    total = row[0]
    entry["row_count"] = total
    for col, non_null in zip(entry["columns"], row[1:]):
        col["null_fraction"] = round(1 - non_null / total, 4) if total else 0.0
