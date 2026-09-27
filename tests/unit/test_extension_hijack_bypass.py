import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"


def test_hijack_bypass_is_loaded_first_in_main_world():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    main = manifest["content_scripts"][0]
    assert main["world"] == "MAIN"
    assert main["run_at"] == "document_start"
    assert main["js"][:4] == [
        "hijack_bypass.js",
        "recaptcha_enterprise.js",
        "recaptcha__en.js",
        "injected.js",
    ]


def test_injected_prefers_pristine_execute_and_neuters_poison_action():
    hijack = (EXT / "hijack_bypass.js").read_text(encoding="utf-8")
    injected = (EXT / "injected.js").read_text(encoding="utf-8")
    content = (EXT / "content.js").read_text(encoding="utf-8")

    assert "__fk_hijack" in hijack
    assert "extension_hijack_detected" in hijack
    assert "executeWithPristine" in injected
    assert "executeWithAssignNeuter" in injected
    assert "extension_hijack_detected" in injected
    assert "createElement('script')" not in content
