from pathlib import Path

import pytest

from agent.comicreels.sign_text import normalize_panel_text_regions, validate_overlay, overlay_filters


def spec():
    return {
        'kind': 'signage', 'text': 'KHÔNG MANG\nTHỨC ĂN BÊN\nNGOÀI VÀO RẠP\nPHIM',
        'source_sha256': 'a' * 64, 'video_sha256': 'b' * 64,
        'source_verified': True, 'geometry_verified': True,
        'evidence': 'original image and every visible scene frame inspected',
        'width': 720, 'height': 1280, 'start_frame': 60, 'end_frame': 120,
        'box': {'x': 310, 'y': 450, 'w': 365, 'h': 330},
    }


def test_sign_is_never_turned_into_a_removal_mask_or_dialogue():
    panel = {'w': 500, 'h': 500, 'dialogues': [], 'speech_regions': [
        {'x': 10, 'y': 20, 'w': 100, 'h': 50, 'kind': 'signage', 'text': 'CẤM VÀO'},
        {'x': 2, 'y': 3, 'w': 20, 'h': 10, 'kind': 'speech_bubble'},
    ]}
    normalized = normalize_panel_text_regions(panel)
    assert [r['kind'] for r in normalized['speech_regions']] == ['speech_bubble']
    assert normalized['text_regions'][0]['text'] == 'CẤM VÀO'
    assert normalized['dialogues'] == []
    assert panel['speech_regions'][0]['kind'] == 'signage'


def test_legacy_ambiguous_caption_is_preserved_for_review():
    result = normalize_panel_text_regions({'speech_regions': [
        {'kind': 'caption', 'x': 1, 'y': 1, 'w': 10, 'h': 10}]})
    assert not result['speech_regions']
    assert result['text_regions'][0]['kind'] == 'unclassified'
    assert result['text_warnings']


@pytest.mark.parametrize('change', [
    {'source_verified': False}, {'geometry_verified': False}, {'kind': 'speech_bubble'},
    {'start_frame': 120}, {'end_frame': 60}, {'text': ''}, {'video_sha256': 'wrong'},
    {'box': {'x': 710, 'y': 450, 'w': 365, 'h': 330}},
])
def test_overlay_rejects_unbound_or_unverified_geometry(change):
    with pytest.raises(ValueError):
        validate_overlay(dict(spec(), **change))


def test_filters_limit_overlay_to_verified_half_open_frame_interval(tmp_path):
    font = Path('C:/Windows/Fonts/comicbd.ttf')
    if not font.is_file():
        pytest.skip('Windows font fixture not installed')
    filters, layout = overlay_filters(spec(), tmp_path, font)
    assert len(filters) == 4
    assert all("enable='gte(n,60)*lt(n,120)'" in f for f in filters)
    assert all('expansion=none' in f for f in filters)
    assert [Path(x['textfile']).read_text(encoding='utf-8') for x in layout['lines']] == spec()['text'].splitlines()
    assert all(x['width'] <= 365 for x in layout['lines'])
