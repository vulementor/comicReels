from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from agent.comicreels import image_ops


def test_verticalize_is_9_16_and_preserves_source_pixels(tmp_path: Path):
    src = tmp_path / "clean.png"
    out = tmp_path / "vertical.png"
    arr = np.zeros((90, 160, 3), dtype=np.uint8)
    arr[:, :, 0] = np.arange(160, dtype=np.uint8)
    arr[:, :, 1] = 80
    Image.fromarray(arr, "RGB").save(src)
    _, box = image_ops.verticalize(src, out)
    with Image.open(out) as im:
        assert im.width * 16 == im.height * 9
    assert image_ops.verify_protected_region(src, out, box)


def test_inpaint_changes_only_mask_pixels(tmp_path: Path):
    source = tmp_path / "crop.png"
    mask = tmp_path / "mask.png"
    clean = tmp_path / "clean.png"
    src = np.full((80, 120, 3), 210, dtype=np.uint8)
    cv2.rectangle(src, (35, 25), (85, 50), (0, 0, 0), -1)
    cv2.imwrite(str(source), src)
    m = np.zeros((80, 120), dtype=np.uint8)
    cv2.rectangle(m, (30, 20), (90, 55), 255, -1)
    cv2.imwrite(str(mask), m)
    image_ops.clean_with_mask(source, mask, clean, radius=3)
    result = cv2.imread(str(clean))
    assert np.array_equal(src[m == 0], result[m == 0])


def test_local_panel_detector_has_safe_full_frame_fallback(tmp_path: Path):
    source = tmp_path / "blank.png"
    Image.new("RGB", (320, 480), "white").save(source)
    assert image_ops.detect_panels(source) == [{
        "x": 0, "y": 0,"width": 320,"height": 480,
        "confidence": 0.25,"display_order": 0,
    }]
