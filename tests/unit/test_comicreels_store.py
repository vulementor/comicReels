import pytest

from agent.comicreels.store import ComicStore


@pytest.mark.asyncio
async def test_store_project_roundtrip(tmp_path, monkeypatch):
    # This test documents the storage contract. Local test setup can monkeypatch
    # module DB_PATH/ROOT to tmp_path before constructing the store.
    import agent.comicreels.store as module
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
