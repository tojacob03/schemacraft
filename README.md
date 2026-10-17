# schemacraft

Turn a database into a Minecraft city you can walk through.

Every table becomes a building, every foreign key a road. The city answers questions you would otherwise ask an ER diagram: where does the data live, what hangs on what, which tables stand alone.

![Chinook as a city, top view](examples/chinook.png)

*The [Chinook](https://github.com/lerocha/chinook-database) sample database from above. Colour is building height.*

## How the database maps to the city

| Database | City |
|---|---|
| table | building |
| row count | height, `4 + 12·log10(rows+1)` blocks |
| column count | footprint, `5 + 2·⌈√columns⌉` blocks square |
| foreign key | road between the two buildings |
| tables linked by foreign keys | neighbours |

## Quick start

```bash
uv run schemacraft inspect sqlite:///tests/fixtures/chinook.sqlite -o model.json
uv run schemacraft layout model.json -o city.json --png city.png
```

`inspect` takes any SQLAlchemy URL (SQLite, Postgres, MySQL, …) and writes a plain JSON model: tables, columns, primary and foreign keys, indexes, exact row counts and the null fraction of every column. `layout` turns that model into a city plan on a block grid.

## Status

- [x] Introspection to a JSON model
- [x] City layout and top-down PNG
- [ ] Export as a `.schem` file to paste with WorldEdit
- [ ] Ready-to-play world built by a headless server
- [ ] Data-quality details: cracked walls for nulls, dark streets for foreign keys without an index

## Development

```bash
uv run pytest
```

The tests check the model against Chinook's published row counts and foreign keys, and check that buildings never overlap and that every foreign key has a road.

Chinook is © Luis Rocha, MIT licensed, see `tests/fixtures/chinook.LICENSE.md`.
