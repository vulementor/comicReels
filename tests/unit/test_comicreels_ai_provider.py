from pathlib import Path

from PIL import Image

from agent.comicreels.ai_provider import prepare_edit_assets, provider_status


def test_ai_canvas_is_vertical_and_preserves_mask_contract(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    src = tmp_path / "panel.png"
    Image.new("RGB", (400, 200), (20, 40, 60)).save(src)

    base = tmp_path / "base.png"
    mask = tmp_path / "mask.png"
    protected, scale = prepare_edit_assets(
        src,
        [{"x": 100, "y": 40, "w": 120, "h": 80}],
        base,
        mask,
    )

    assert scale == 1.0
    with Image.open(base) as image:
        assert image.height > image.width
        assert abs((image.width / image.height) - (9 / 16)) < 0.02
    with Image.open(mask) as image:
        alpha = image.getchannel("A")
        outside = alpha.getpixel((0, 0))
        inside_source = alpha.getpixel((protected["x"] + 20, protected["y"] + 20))
        inside_edit = alpha.getpixel((protected["x"] + 140, protected["y"] + 80))
        assert outside == 0
        assert inside_source == 255
        assert inside_edit == 0


def test_provider_status_does_not_expose_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-key")
    status = provider_status()
    assert status["configured"] is True
    assert "secret-test-key" not in repr(status)
