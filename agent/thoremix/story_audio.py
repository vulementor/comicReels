"""Audio diagnostics only: the source transcript remains authoritative."""
from __future__ import annotations

import re


def tokens(value):
    from agent.comicreels.prompts import spoken_text
    return re.findall(r'[^\W_]+', spoken_text(value).casefold(), re.UNICODE)


def duplicate_intervals(dialogues, words, duration):
    """Keep each complete source line once; silence only a later exact repetition.

    Unknown/missing words, uncertain timestamps or overlaps fail closed. The ASR
    text never rewrites source dialogue or authorizes new lines.
    """
    expected=[tokens(d['text']) for d in sorted(dialogues,key=lambda d:(d['panel_index'],d['display_order']))]
    if not expected or any(not line for line in expected):
        raise ValueError('SOURCE_DIALOGUE_EMPTY')
    actual=[]
    for word in words:
        items=tokens(word['word'])
        if (len(items)!=1 or not 0<=word['start']<word['end']<=duration
                or word.get('probability',0)<.5):
            raise ValueError('AUDIO_WORD_UNCERTAIN')
        actual.append(items[0])
    cursor,line,seen,intervals=0,0,[],[]
    while cursor<len(actual):
        if line<len(expected) and actual[cursor:cursor+len(expected[line])]==expected[line]:
            length=len(expected[line]);seen.append(expected[line]);line+=1
        else:
            matches=[s for s in seen if actual[cursor:cursor+len(s)]==s]
            if len(matches)!=1:
                raise ValueError('AUDIO_SOURCE_MISMATCH')
            length=len(matches[0])
            start,end=words[cursor]['start'],words[cursor+length-1]['end']
            if (cursor and words[cursor-1]['end']>start) or (cursor+length<len(words) and words[cursor+length]['start']<end):
                raise ValueError('AUDIO_OVERLAP_UNCERTAIN')
            intervals.append([start,end])
        cursor+=length
    if line!=len(expected):
        raise ValueError('AUDIO_DIALOGUE_MISSING')
    return intervals
