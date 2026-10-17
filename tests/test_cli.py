import sys

import pytest

from schemacraft import cli


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["schemacraft", *args])
    cli.main()


def test_build_writes_everything(monkeypatch, tmp_path, chinook_url):
    saves = tmp_path / "saves"
    saves.mkdir()
    monkeypatch.setattr(cli, "_saves_dir", lambda: saves)
    out = tmp_path / "out"
    run(monkeypatch, "build", chinook_url, "-o", str(out), "--install")

    for name in ("model.json", "city.json", "city.png", "chinook.schem", "world/level.dat", "world/icon.png"):
        assert (out / name).exists(), name
    assert list((out / "world" / "region").glob("r.*.mca"))
    assert (saves / "chinook" / "level.dat").exists()

    with pytest.raises(SystemExit, match="already exists"):  # never overwrite a save
        run(monkeypatch, "build", chinook_url, "-o", str(out), "--install")


def test_step_by_step(monkeypatch, tmp_path, library_url):
    model, city = tmp_path / "model.json", tmp_path / "city.json"
    run(monkeypatch, "inspect", library_url, "-o", str(model), "--sample", "2")
    assert '"sample"' in model.read_text()
    run(monkeypatch, "layout", str(model), "-o", str(city), "--png", str(tmp_path / "city.png"))
    run(monkeypatch, "schem", str(model), str(city), "-o", str(tmp_path / "library.schem"))
    run(monkeypatch, "world", str(model), str(city), "-o", str(tmp_path / "world"), "--name", "Library")
    assert (tmp_path / "world" / "level.dat").exists() and (tmp_path / "library.schem").exists()


def test_default_name():
    assert cli._default_name("sqlite:///data/chinook.sqlite") == "chinook"
    assert cli._default_name("postgresql+psycopg://u:secret@host/shop") == "shop"
    assert cli._slug("My DB: v2") == "My-DB-v2"
