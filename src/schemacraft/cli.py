import argparse
import json
import os
import platform
import re
import shutil
from pathlib import Path

from sqlalchemy.engine import make_url

from schemacraft.anvil import write_world
from schemacraft.blocks import build
from schemacraft.introspect import introspect
from schemacraft.layout import layout
from schemacraft.render import render_icon, render_png
from schemacraft.schem import write_schem


def main() -> None:
    parser = argparse.ArgumentParser(prog="schemacraft", description="Turn a database into a Minecraft city.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="database URL -> world, schematic and top view in one go")
    p.add_argument("url", help="SQLAlchemy URL, e.g. sqlite:///chinook.sqlite")
    p.add_argument("-o", "--out", help="output folder (default: ./<name>)")
    p.add_argument("--name", help="world name (default: database name)")
    p.add_argument("--install", action="store_true", help="also copy the world into Minecraft's saves folder")
    p.add_argument("--seed", type=int, default=42)

    p = sub.add_parser("inspect", help="read a database into model.json")
    p.add_argument("url")
    p.add_argument("-o", "--out", default="model.json")

    p = sub.add_parser("layout", help="plan the city from model.json")
    p.add_argument("model", nargs="?", default="model.json")
    p.add_argument("-o", "--out", default="city.json")
    p.add_argument("--png", help="also write a top-down PNG")
    p.add_argument("--seed", type=int, default=42)

    for cmd, help_ in (("world", "write a playable world folder"), ("schem", "write a WorldEdit .schem file")):
        p = sub.add_parser(cmd, help=help_)
        p.add_argument("model", nargs="?", default="model.json")
        p.add_argument("city", nargs="?", default="city.json")
        p.add_argument("-o", "--out", required=True)
        p.add_argument("--name", default="schemacraft")

    args = parser.parse_args()
    if args.command == "build":
        _build(args)
    elif args.command == "inspect":
        model = introspect(args.url)
        Path(args.out).write_text(json.dumps(model, indent=2))
        print(f"{len(model['tables'])} tables -> {args.out}")
    elif args.command == "layout":
        city = layout(_read(args.model), seed=args.seed)
        Path(args.out).write_text(json.dumps(city, indent=2))
        print(f"{len(city['buildings'])} buildings, {len(city['roads'])} roads -> {args.out}")
        if args.png:
            render_png(city, args.png)
            print(f"top view -> {args.png}")
    else:
        model, city = _read(args.model), _read(args.city)
        blocks, spawn = build(model, city, args.name)
        if args.command == "world":
            write_world(blocks, Path(args.out), args.name, spawn, icon=lambda p: render_icon(city, p))
        else:
            write_schem(blocks, Path(args.out))
        print(f"{args.command} -> {args.out}")


def _build(args) -> None:
    name = args.name or _default_name(args.url)
    out = Path(args.out or _slug(name))
    out.mkdir(parents=True, exist_ok=True)

    model = introspect(args.url)
    (out / "model.json").write_text(json.dumps(model, indent=2))
    print(f"inspected {len(model['tables'])} tables")
    if not model["tables"]:
        raise SystemExit("the database has no tables")

    city = layout(model, seed=args.seed)
    (out / "city.json").write_text(json.dumps(city, indent=2))
    render_png(city, out / "city.png")
    print(f"planned {len(city['buildings'])} buildings and {len(city['roads'])} roads -> {out / 'city.png'}")

    blocks, spawn = build(model, city, name)
    size = write_schem(blocks, out / f"{_slug(name)}.schem")
    print(f"schematic {size[0]}x{size[1]}x{size[2]} -> {out / (_slug(name) + '.schem')}")

    world = out / "world"
    if world.exists():
        shutil.rmtree(world)
    write_world(blocks, world, name, spawn, icon=lambda p: render_icon(city, p))
    print(f"world -> {world}")

    if args.install:
        target = _saves_dir() / name
        if target.exists():
            raise SystemExit(f"{target} already exists; pick another --name or remove it")
        shutil.copytree(world, target)
        print(f"installed -> {target}\nopen Minecraft Java, Singleplayer, '{name}'")


def _read(path):
    return json.loads(Path(path).read_text())


def _default_name(url: str) -> str:
    database = make_url(url).database or "schemacraft"
    return Path(database).stem or "schemacraft"


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "schemacraft"


def _saves_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        root = Path.home() / "Library" / "Application Support" / "minecraft"
    elif system == "Windows":
        root = Path(os.environ["APPDATA"]) / ".minecraft"
    else:
        root = Path.home() / ".minecraft"
    if not root.exists():
        raise SystemExit(f"Minecraft folder not found at {root}")
    return root / "saves"
