import importlib

import aiosqlite
import pytest

from agent.comicreels.store import ComicStore

store_module = importlib.import_module("agent.comicreels.store")


@pytest.mark.asyncio
async def test_store_project_roundtrip(tmp_path, monkeypatch):
    # This test documents the storage contract. Local test setup can monkeypatch
    # module DB_PATH/ROOT to tmp_path before constructing the store.
    import importlib
    module = importlib.import_module("agent.comicreels.store")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "comicreels.db")
    s = ComicStore()
    project = await s.create_project(
        project_id="p", name="Demo", source_path=str(tmp_path / "source.png"),
        sha256="deadbeef", mime="image/png", width=100, height=200,
    )
    assert project["id"] == "p"
    loaded = await s.get_project("p")
    assert loaded["project"]["source_sha256"] == "deadbeef"
    assert loaded["panels"] == []


@pytest.mark.asyncio
async def test_store_persists_panel_visual_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "ROOT", tmp_path / "comicreels")
    monkeypatch.setattr(store_module, "DB_PATH", tmp_path / "comicreels" / "comicreels.db")
    s = ComicStore()
    await s.create_project(
        project_id="p-anchor",
        name="Anchor",
        source_path=str(tmp_path / "source.png"),
        sha256="a" * 64,
        mime="image/png",
        width=100,
        height=200,
    )
    await s.replace_analysis(
        "p-anchor",
        panels=[{
            "x": 0, "y": 0, "w": 100, "h": 200,
            "mask": [{"x": 1, "y": 2, "w": 10, "h": 20}],
            "visual_anchor": "CHAR_1 đứng bên trái, quay sang phải.",
        }],
        dialogues=[],
    )

    loaded = await s.get_project("p-anchor")

    assert loaded["panels"][0]["visual_anchor"] == "CHAR_1 đứng bên trái, quay sang phải."


@pytest.mark.asyncio
async def test_store_migrates_legacy_panel_table_with_visual_anchor(tmp_path, monkeypatch):
    root = tmp_path / "comicreels"
    db_path = root / "comicreels.db"
    root.mkdir(parents=True)
    legacy_schema = store_module.SCHEMA.replace("    visual_anchor TEXT,\n", "")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(legacy_schema)
        await db.commit()

    monkeypatch.setattr(store_module, "ROOT", root)
    monkeypatch.setattr(store_module, "DB_PATH", db_path)
    s = ComicStore()
    await s.init()

    async with aiosqlite.connect(db_path) as db:
        columns = {
            str(row[1])
            for row in await (await db.execute("PRAGMA table_info(comic_panel)")).fetchall()
        }

    assert "visual_anchor" in columns
