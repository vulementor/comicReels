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


@pytest.mark.asyncio
async def test_apply_visual_anchors_invalidates_all_portraits_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "ROOT", tmp_path / "comicreels")
    monkeypatch.setattr(store_module, "DB_PATH", tmp_path / "comicreels" / "comicreels.db")
    s = ComicStore()
    await s.create_project(
        project_id="p-backfill",
        name="Backfill",
        source_path=str(tmp_path / "source.png"),
        sha256="b" * 64,
        mime="image/png",
        width=1200,
        height=1600,
    )
    await s.replace_analysis(
        "p-backfill",
        panels=[
            {"x": 0, "y": 0, "w": 1200, "h": 500, "mask": []},
            {"x": 0, "y": 500, "w": 1200, "h": 500, "mask": []},
            {"x": 0, "y": 1000, "w": 1200, "h": 600, "mask": []},
        ],
        dialogues=[],
    )
    seeded = await s.get_project("p-backfill")
    for index, panel in enumerate(seeded["panels"]):
        await s.update_panel(
            panel["id"],
            portrait_path=f"/tmp/legacy-{index}.png",
            portrait_sha256=str(index + 1) * 64,
            approved_sha256=None,
            protected_json='{"x":0,"y":0,"w":576,"h":1024}',
            status="AI_IMAGE_READY",
        )

    await s.apply_visual_anchors_and_invalidate_portraits(
        "p-backfill",
        {
            0: "Anchor panel zero with enough geometry to distinguish the source panel.",
            1: "Anchor panel one with enough geometry to distinguish the source panel.",
            2: "Anchor panel two with enough geometry to distinguish the source panel.",
        },
    )

    loaded = await s.get_project("p-backfill")
    assert loaded["project"]["status"] == "EXTRACTED"
    assert [panel["status"] for panel in loaded["panels"]] == ["EXTRACTED"] * 3
    assert all(panel["portrait_path"] is None for panel in loaded["panels"])
    assert all(panel["portrait_sha256"] is None for panel in loaded["panels"])
    assert all(panel["approved_sha256"] is None for panel in loaded["panels"])
    assert all(panel["protected"] is None for panel in loaded["panels"])
    assert [panel["visual_anchor"] for panel in loaded["panels"]] == [
        "Anchor panel zero with enough geometry to distinguish the source panel.",
        "Anchor panel one with enough geometry to distinguish the source panel.",
        "Anchor panel two with enough geometry to distinguish the source panel.",
    ]


@pytest.mark.asyncio
async def test_apply_visual_anchors_rejects_partial_set_without_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "ROOT", tmp_path / "comicreels")
    monkeypatch.setattr(store_module, "DB_PATH", tmp_path / "comicreels" / "comicreels.db")
    s = ComicStore()
    await s.create_project(
        project_id="p-partial",
        name="Partial",
        source_path=str(tmp_path / "source.png"),
        sha256="c" * 64,
        mime="image/png",
        width=100,
        height=200,
    )
    await s.replace_analysis(
        "p-partial",
        panels=[
            {"x": 0, "y": 0, "w": 100, "h": 100, "mask": []},
            {"x": 0, "y": 100, "w": 100, "h": 100, "mask": []},
        ],
        dialogues=[],
    )
    seeded = await s.get_project("p-partial")
    for panel in seeded["panels"]:
        await s.update_panel(
            panel["id"],
            portrait_path="/tmp/legacy.png",
            portrait_sha256="d" * 64,
            status="AI_IMAGE_READY",
        )

    with pytest.raises(ValueError, match="does not match"):
        await s.apply_visual_anchors_and_invalidate_portraits(
            "p-partial",
            {0: "Only one anchor should not be accepted for a two-panel project."},
        )

    loaded = await s.get_project("p-partial")
    assert [panel["status"] for panel in loaded["panels"]] == ["AI_IMAGE_READY", "AI_IMAGE_READY"]
    assert all(panel["visual_anchor"] is None for panel in loaded["panels"])
    assert all(panel["portrait_path"] == "/tmp/legacy.png" for panel in loaded["panels"])


@pytest.mark.asyncio
async def test_apply_visual_anchor_validation_invalidates_only_changed_panel(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "ROOT", tmp_path / "comicreels")
    monkeypatch.setattr(store_module, "DB_PATH", tmp_path / "comicreels" / "comicreels.db")
    s = ComicStore()
    await s.create_project(
        project_id="p-validate",
        name="Validate",
        source_path=str(tmp_path / "source.png"),
        sha256="e" * 64,
        mime="image/png",
        width=1200,
        height=1600,
    )
    await s.replace_analysis(
        "p-validate",
        panels=[
            {"x": 0, "y": 0, "w": 1200, "h": 500, "mask": [], "visual_anchor": "anchor-0-current-source-geometry"},
            {"x": 0, "y": 500, "w": 1200, "h": 500, "mask": [], "visual_anchor": "anchor-1-current-source-geometry"},
            {"x": 0, "y": 1000, "w": 1200, "h": 600, "mask": [], "visual_anchor": "anchor-2-current-source-geometry"},
        ],
        dialogues=[],
    )
    seeded = await s.get_project("p-validate")
    for index, panel in enumerate(seeded["panels"]):
        await s.update_panel(
            panel["id"],
            portrait_path=f"/tmp/portrait-{index}.png",
            portrait_sha256=str(index + 3) * 64,
            status="AI_IMAGE_READY",
        )

    changed = await s.apply_visual_anchor_validation(
        "p-validate",
        {
            0: {"matches_source": True, "corrected_anchor": ""},
            1: {"matches_source": True, "corrected_anchor": ""},
            2: {
                "matches_source": False,
                "corrected_anchor": "panel 3 corrected: orange bull turned left; rabbit and cow remain on bed right",
            },
        },
    )

    loaded = await s.get_project("p-validate")
    assert changed == [2]
    assert loaded["panels"][0]["status"] == "AI_IMAGE_READY"
    assert loaded["panels"][0]["portrait_path"] == "/tmp/portrait-0.png"
    assert loaded["panels"][1]["status"] == "AI_IMAGE_READY"
    assert loaded["panels"][1]["portrait_path"] == "/tmp/portrait-1.png"
    assert loaded["panels"][2]["status"] == "EXTRACTED"
    assert loaded["panels"][2]["portrait_path"] is None
    assert loaded["panels"][2]["portrait_sha256"] is None
    assert "turned left" in loaded["panels"][2]["visual_anchor"]
