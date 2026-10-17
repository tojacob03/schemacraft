"""Read a database's structure and basic statistics into a plain JSON model.

The model knows nothing about Minecraft; layout and export build on it.
"""

from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.sql import column, table


def introspect(url: str) -> dict:
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
    if insp.dialect.name == "sqlite":
        return [None]
    skip = {"information_schema", "pg_catalog", "pg_toast"}
    return [s for s in insp.get_schema_names() if s not in skip]


def _table(insp, conn, schema, name, kind) -> dict:
    pk = set(insp.get_pk_constraint(name, schema=schema)["constrained_columns"])
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
            }
            for fk in insp.get_foreign_keys(name, schema=schema)
        ],
        "indexes": [
            {"name": ix["name"], "columns": ix["column_names"], "unique": bool(ix["unique"])}
            for ix in insp.get_indexes(name, schema=schema)
        ],
    }
    if kind == "table":
        _add_counts(conn, schema, entry)
    return entry


def _add_counts(conn, schema, entry) -> None:
    """Exact row count and per-column null fraction in a single scan."""
    names = [c["name"] for c in entry["columns"]]
    t = table(entry["name"], *[column(n) for n in names], schema=schema)
    row = conn.execute(select(func.count(), *[func.count(t.c[n]) for n in names])).one()
    total = row[0]
    entry["row_count"] = total
    for col, non_null in zip(entry["columns"], row[1:]):
        col["null_fraction"] = round(1 - non_null / total, 4) if total else 0.0
