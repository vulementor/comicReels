from pathlib import Path

from PIL import Image

from agent.comicreels.images import clean_with_rect_masks, portrait_9_16, sha256_file


def _make(path: Path):
    im = Image.new("RGB", (90, 60), (10, 20, 30))
    for x in range(20, 70):
        for y in range(15, 45):
            im.putpixel((x, y), (200, 100, 50))
    im.save(path)


def test_portrait_preserves_source_pixels(tmp_path):
    src = tmp_path / "src.png"
    out = tmp_path / "portrait.png"
    _make(src)
    _, protected, digest = portrait_9_16(src, out)
    assert digest == sha256_file(out)
    with Image.open(src) as original, Image.open(out) as portrait:
        crop = portrait.crop((
            protected["x"], protected["y"],
            protected["x"] + protected["w"], protected["y"] + protected["h"],
        ))
        assert list(crop.getdata()) == list(original.convert("RGB").getdata())
        assert portrait.width * 16 == portrait.height * 9


def test_clean_changes_only_mask(tmp_path):
    src = tmp_path / "src.png"
    out = tmp_path / "clean.png"
    _make(src)
    mask = {"x": 30, "y": 20, "w": 20, "h": 10}
    clean_with_rect_masks(src, [mask], out)
    with Image.open(src) as a, Image.open(out) as b:
        a = a.convert("RGB"); b = b.convert("RGB")
        for y in range(a.height):
            for x in range(a.width):
                inside = 30 <= x < 50 and 20 <= y < 30
                if not inside:
                    assert a.getpixel((x, y)) == b.getpixel((x, y))
