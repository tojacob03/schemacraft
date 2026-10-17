import argparse
import json
from pathlib import Path

from schemacraft.introspect import introspect
from schemacraft.layout import layout
from schemacraft.render import render_png


def main() -> None:
    parser = argparse.ArgumentParser(prog="schemacraft", description="Turn a database into a Minecraft city.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="read a database into model.json")
    p.add_argument("url", help="SQLAlchemy URL, e.g. sqlite:///chinook.sqlite")
    p.add_argument("-o", "--out", default="model.json")

    p = sub.add_parser("layout", help="plan the city from model.json")
    p.add_argument("model", nargs="?", default="model.json")
    p.add_argument("-o", "--out", default="city.json")
    p.add_argument("--png", help="also write a top-down PNG")
    p.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()
    if args.command == "inspect":
        model = introspect(args.url)
        Path(args.out).write_text(json.dumps(model, indent=2))
        print(f"{len(model['tables'])} tables -> {args.out}")
    else:
        city = layout(json.loads(Path(args.model).read_text()), seed=args.seed)
        Path(args.out).write_text(json.dumps(city, indent=2))
        print(f"{len(city['buildings'])} buildings, {len(city['roads'])} roads -> {args.out}")
        if args.png:
            render_png(city, args.png)
            print(f"top view -> {args.png}")
