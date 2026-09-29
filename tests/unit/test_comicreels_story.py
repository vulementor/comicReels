import pytest

from agent.comicreels.prompts import story_timeline, story_video_prompt


def panel(order, **changes):
    return dict(display_order=order, visual_anchor=f'Bố cục khung {order + 1}',
                dialogues=[], **changes)


def test_four_panels_stay_in_one_ten_second_story_in_reading_order():
    prompt = story_video_prompt([panel(3), panel(0), panel(2), panel(1)])
    assert 'ONE STORY / ONE VIDEO / 10 seconds' in prompt
    assert prompt.index('0-2.5s') < prompt.index('2.5-5s') < prompt.index('5-7.5s') < prompt.index('7.5-10s')
    for i in range(1, 5):
        assert f'REFERENCE {i}' in prompt
    assert 'KHÔNG CÓ LỜI THOẠI' in prompt
    assert 'bong bóng' in prompt
    assert 'không diễn lại' in prompt
    assert 'Tại đúng 2.5s, cắt thẳng sang ảnh 2' in prompt
    assert 'không hòa chúng thành một cảnh dài' in prompt
    assert 'Giữ nguyên tư thế tay/chân' in prompt


def test_story_preserves_each_verified_utterance_once():
    one = panel(0)
    one['dialogues'] = [dict(display_order=0, speaker_id='THO', text='Đi thôi!', verified=True)]
    prompt = story_video_prompt([one, panel(1)])
    assert prompt.count('Đi thôi!') == 1
    assert 'THO' in prompt


def test_line_break_notation_has_identical_speech_budget_and_words():
    one=panel(0)
    line=dict(display_order=0,speaker_id='THO',text=r'ĐỐI VỚI ANH EM\nLUÔN LÀ THỨ NHẤT',verified=True)
    one['dialogues']=[line]
    timeline=story_timeline([one,panel(1)])
    prompt=story_video_prompt([one,panel(1)])
    assert 'ĐỐI VỚI ANH EM LUÔN LÀ THỨ NHẤT' in prompt
    assert '\\n' in line['text']
    line['text']=line['text'].replace('\\n','\n')
    assert story_timeline([one,panel(1)])==timeline


@pytest.mark.parametrize('panels', [[], [panel(0), panel(0)], [panel(0), panel(2)]])
def test_story_does_not_infer_missing_or_ambiguous_panel_order(panels):
    with pytest.raises(ValueError):
        story_video_prompt(panels)


def test_unverified_dialogue_or_overlong_story_cannot_silently_become_multiple_clips():
    one = panel(0)
    one['dialogues'] = [dict(text='Không rõ chữ', speaker_id='THO', verified=False)]
    with pytest.raises(ValueError, match='DIALOGUE_UNVERIFIED'):
        story_video_prompt([one])


@pytest.mark.parametrize('verified', ['false', 'unverified', 1.0, 2])
def test_dialogue_requires_explicit_boolean_verification(verified):
    one = panel(0)
    one['dialogues'] = [dict(text='Đi thôi!', speaker_id='THO', verified=verified)]
    with pytest.raises(ValueError, match='DIALOGUE_UNVERIFIED'):
        story_video_prompt([one])


def test_sqlite_verification_flag_is_accepted_but_long_dialogue_is_rejected():
    one = panel(0)
    one['dialogues'] = [dict(text='Đi thôi!', speaker_id='THO', verified=1)]
    assert 'Đi thôi!' in story_video_prompt([one])
    one['dialogues'] = [dict(text=' '.join(['lời'] * 100), speaker_id='THO', verified=True)]
    with pytest.raises(ValueError, match='STORY_DIALOGUE_TOO_LONG'):
        story_video_prompt([one])


def test_uneven_dialogue_receives_time_without_dropping_silent_panels_or_words():
    from agent.thoremix.story_operations import normalize_analysis
    texts = ['ÚI CÓ BÃI CỨT KÌA LÙI LẠI ĐI BẠN ƠI!', 'ẦY..',
             'ỦA CÓ GÌ ĐÂU BẠN?', 'CÓ CON CHỒN LÙI.']
    lines = [dict(text=text, speaker_id='THO' if i in (0, 3) else 'CHON',
                  panel_index=[0, 0, 2, 3][i], display_order=i)
             for i, text in enumerate(texts)]
    analysis = normalize_analysis(dict(
        panels=[dict(order=i, confidence=.99, visual_anchor='original') for i in range(4)],
        dialogues=lines))
    panels = analysis['panels']
    timeline = story_timeline(panels)
    assert timeline[0][0] == 0 and timeline[-1][1] == 10
    assert all(timeline[i][1] == timeline[i + 1][0] for i in range(3))
    assert timeline[0][1] > 4.5
    for item, (start, end) in zip(panels, timeline):
        assert end - start >= .75
        assert end - start + 1e-9 >= sum(len(d['text'].split()) for d in item['dialogues']) / 2.6
        for line in item['dialogues']:
            line['verified'] = True
    prompt = story_video_prompt(panels)
    assert all(prompt.count(text) == 1 for text in texts)
    assert all(f'REFERENCE {i}' in prompt for i in range(1, 5))


def test_timing_keeps_a_silent_beat_and_rejects_speech_that_uses_it_up():
    panels = [panel(i) for i in range(4)]
    panels[0]['dialogues'] = [dict(text=' '.join(['lời'] * 24))]
    with pytest.raises(ValueError, match='STORY_DIALOGUE_TOO_LONG'):
        story_timeline(panels)
