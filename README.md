# schemacraft

Turn a database into a Minecraft city you can walk through.

Every table becomes a building, every foreign key a road. Walk in through the door and the columns hang on the walls. The city answers questions you would otherwise ask an ER diagram: where does the data live, what hangs on what, which tables stand alone, and where the data is in bad shape.

![Chinook as a city, top view](examples/chinook.png)

*The [Chinook](https://github.com/lerocha/chinook-database) sample database from above. Colour is building height. [Download the playable world](examples/chinook-world.zip).*

## Try it

You need [uv](https://docs.astral.sh/uv/) and Minecraft Java Edition.

```bash
uvx --from git+https://github.com/tojacob03/schemacraft schemacraft build sqlite:///path/to/your.db --install
```

Open Minecraft, choose Singleplayer and the world named after your database. You start in creative mode on a street in the middle of the city.

Other databases need their driver:

```bash
uvx --from 'schemacraft[postgres] @ git+https://github.com/tojacob03/schemacraft' schemacraft build postgresql+psycopg://user:pass@host/db
uvx --from 'schemacraft[duckdb] @ git+https://github.com/tojacob03/schemacraft' schemacraft build duckdb:///analytics.duckdb
uvx --from 'schemacraft[mysql] @ git+https://github.com/tojacob03/schemacraft' schemacraft build mysql+pymysql://user:pass@host/db
```

`build` writes a folder named after the database:

| File | What it is |
|---|---|
| `world/` | playable world; `--install` copies it into Minecraft's saves folder (never overwrites) |
| `<name>.schem` | the city as a schematic to paste with WorldEdit (`//schem load`, then `//paste` on flat ground) |
| `city.png` | top view |
| `model.json` | everything read from the database |
| `city.json` | the city plan: building and road positions |

Without `--install`, copy `world/` into your saves folder yourself: `~/Library/Application Support/minecraft/saves` on macOS, `%APPDATA%\.minecraft\saves` on Windows, `~/.minecraft/saves` on Linux.

## How the database maps to the city

| Database | City |
|---|---|
| table | stone building; a view is a glass building |
| row count | height, `4 + 12·log10(rows+1)` blocks |
| column count | footprint, `5 + 2·⌈√columns⌉` blocks square |
| column | a sign inside: name, type, `PK`/`FK`, share of nulls |
| foreign key | road between the two buildings, with a door at each end |
| tables linked by foreign keys | neighbours |
| schema | district; every schema has its own roof colour |
| nulls | cracked bricks: the more nulls a table holds, the more cracks |
| foreign key without an index | dark blackstone road with broken lamps |

The last one is a real performance finding. A foreign key whose columns do not lead the primary key or any index forces a scan whenever the parent row is deleted or joined from that side. In Postgres that is a classic cause of slow deletes. (DuckDB joins by hashing, so there a dark road is rarely a problem.)

## How it works

```
database ──► inspect ──► model.json ──► layout ──► city.json ──► blocks ──► world/ · .schem · city.png
```

- **inspect** reads structure through SQLAlchemy (DuckDB through its own catalog). Row counts and null shares come from one scan per table. Postgres tables above a million rows use the planner's statistics (`reltuples`, `pg_stats.null_frac`) instead, marked with `~` on the door sign.
- **layout** gives the biggest web of linked tables a force-directed layout, then snaps it to a block grid so no two buildings come closer than four blocks. Smaller groups and tables without foreign keys dock onto the edge of their schema's district afterwards, member next to member, instead of drifting into an empty outer ring. Roads are found with A*, and a road that runs along an existing one costs less, so roads merge into streets.
- **world** writes the Anvil format of Minecraft 1.21.4 (data version 4189). Newer versions upgrade the world when you open it, the same way they upgrade any older save. Light is left to the game.

## A big one: GitLab

GitLab publishes its database schema ([`db/structure.sql`](https://gitlab.com/gitlab-org/gitlab/-/blob/master/db/structure.sql)). Loaded into an empty Postgres it has 1,468 tables, 15 views and 2,381 foreign keys; schemacraft turns it into a city of 828 × 961 blocks in 22 seconds on a laptop. The tables are empty, so every building has the same height; the top-left block is the `gitlab_partitions_static` schema.

![GitLab's schema as a city, top view](examples/gitlab.png)

## Development

```bash
uv sync --all-extras
uv run pytest
```

The tests check:

- the model against Chinook's published row counts and foreign keys, plus a library database with an unindexed foreign key, a view and many nulls
- Postgres (embedded through `pgserver`, with two schemas and 1.2 million rows) and DuckDB
- that buildings never overlap and every foreign key has an unbroken road
- the written world, read back with a separate minimal Anvil reader (`tests/mcread.py`). That reader was checked once against chunks written by Minecraft 26.3 itself: decoded blocks and Minecraft's own heightmaps agreed in every chunk
- the schematic, block by block against the world

Every push builds the Chinook world in CI and attaches it to the run.

## Limits

- MySQL is supported through SQLAlchemy but not covered by tests.
- Counting rows scans every table except big Postgres ones; on a large MySQL or SQLite database `inspect` takes a while.
- Column signs fill the walls storey by storey. A wide table with few rows gets a low building, and when its walls run out the last sign reads “+N more”.
- The world has not been opened in every Minecraft version; it is written for 1.21.4 and relies on Minecraft's own upgrade for newer ones.

Chinook is © Luis Rocha, MIT licensed, see `tests/fixtures/chinook.LICENSE.md`. schemacraft is MIT licensed.
