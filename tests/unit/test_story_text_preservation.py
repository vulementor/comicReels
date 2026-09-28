import pytest

from agent.thoremix.story_operations import (
    normalize_analysis,
    required_text_regions,
    text_preservation_verified,
)


def analysis_with(panel):
    return {'panels':[{'x':0,'y':0,'w':100,'h':100,'order':0,'confidence':.99,
                       'visual_anchor':'one exact panel',**panel}],
            'dialogues':[],'characters':[],'warnings':[]}


def test_legacy_signage_in_speech_regions_is_preserved_not_masked():
    data=normalize_analysis(analysis_with({'speech_regions':[{
        'x':10,'y':20,'w':70,'h':30,'kind':'signage',
        'text':'KHÔNG MANG THỨC ĂN','confidence':.99}]}))
    panel=data['panels'][0]
    assert panel['speech_regions']==[]
    assert panel['text_regions']==[{
        'x':10,'y':20,'w':70,'h':30,'kind':'signage',
        'text':'KHÔNG MANG THỨC ĂN','confidence':.99}]
    assert required_text_regions(data)==[{
        'panel_index':0,'kind':'signage','text':'KHÔNG MANG THỨC ĂN'}]


def test_ambiguous_legacy_caption_stops_instead_of_becoming_deletion_mask():
    with pytest.raises(ValueError,match='UNCERTAIN_SOURCE_TEXT'):
        normalize_analysis(analysis_with({'speech_regions':[{
            'x':10,'y':20,'w':70,'h':30,'kind':'caption',
            'text':'KHÔNG MANG THỨC ĂN','confidence':.99}]}))


def test_low_confidence_source_text_stops_before_generation():
    with pytest.raises(ValueError,match='UNCERTAIN_SOURCE_TEXT'):
        normalize_analysis(analysis_with({'text_regions':[{
            'x':10,'y':20,'w':70,'h':30,'kind':'signage',
            'text':'KHÔNG MANG THỨC ĂN','confidence':.5}]}))


def test_text_preservation_requires_exact_panel_kind_text_and_present_true():
    analysis=normalize_analysis(analysis_with({'text_regions':[{
        'x':10,'y':20,'w':70,'h':30,'kind':'signage',
        'text':'KHÔNG MANG\nTHỨC ĂN','confidence':.99}]}))
    assert text_preservation_verified(analysis,{'preserved_text':[{
        'panel_index':0,'kind':'signage','text':'KHÔNG MANG\nTHỨC ĂN','present':True}]})
    assert not text_preservation_verified(analysis,{'preserved_text':[{
        'panel_index':0,'kind':'signage','text':'KHÔNG MANG THỨC ĂN','present':True}]})
    assert not text_preservation_verified(analysis,{'preserved_text':[{
        'panel_index':0,'kind':'signage','text':'KHÔNG MANG\nTHỨC ĂN','present':False}]})
    assert not text_preservation_verified(analysis,{})


def test_no_source_text_needs_no_false_proof():
    analysis=normalize_analysis(analysis_with({'speech_regions':[],'text_regions':[]}))
    assert required_text_regions(analysis)==[]
    assert text_preservation_verified(analysis,{})
