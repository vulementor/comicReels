import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from agent.thoremix import core
from agent.thoremix.config import Settings, atomic_json
from agent.thoremix.core import Campaign, sha256


@pytest.fixture
def correction_case(tmp_path, monkeypatch):
    from agent.thoremix import media_correction as mod

    input_dir=tmp_path/'input'; input_dir.mkdir()
    settings=Settings(root=str(tmp_path/'app'),input_dir=str(input_dir))
    settings.save()
    monkeypatch.setattr(core,'validate_media',lambda *a,**k:{'full_decode':True,'width':720,'height':1280,'duration_s':10.0})
    monkeypatch.setattr(mod,'validate_media',lambda *a,**k:{'full_decode':True,'width':720,'height':1280,'duration_s':10.0})

    source=input_dir/'story.jpg'
    Image.new('RGB',(100,200),'white').save(source)
    frames=[]
    for i,color in enumerate(('red','green','blue','yellow'),1):
        path=tmp_path/f'frame-{i}.png'
        Image.new('RGB',(100,200),color).save(path)
        frames.append(path)
    old_video=tmp_path/'old.mp4'; old_video.write_bytes(b'old-faulty-audio-video'*100)
    candidate=tmp_path/'candidate.mp4'; candidate.write_bytes(b'clean-native-audio-video'*100)
    native_sha='d'*64

    campaign=Campaign(settings)
    job=campaign.reserve('manual-correction',source=source)
    old=campaign.finalize(job['id'],old_video,children=frames,metadata={
        'title':'Clip','caption':'Caption','description':'Description',
        'qa':{'release_ready':True,'decoded_audio_all_zero':True},
        'affiliate':{'state':'verified','url':'https://s.shopee.vn/demo',
                     'disclosure':'affiliate','comment':'product\nhttps://s.shopee.vn/demo'},
        'generation':{'kind':'native_flow_video','download_sha256':native_sha},
        'youtube':{'made_for_kids':False},
        'publication_targets':['facebook','tiktok','youtube'],
    })
    campaign.update(job['id'],'publishing')
    job=campaign.get(job['id'])
    folder=Path(job['package_dir'])
    package_path=folder/'package.json'
    current_sha=sha256(package_path)
    publication_sha='b'*64

    operation_ids={
        'facebook':'fbop',
        'tiktok':'ttop',
        'youtube':'ytop',
        'youtube_comment':'ytcomment',
    }
    publication={'schema_version':1,'package_sha256':publication_sha,
        'source_sha256':old['source_sha256'],'complete':False,'platforms':{
            'facebook':{'publication':{'state':'unknown','operation_id':'fbop',
                'idempotency_key':f"thoremix:{old['source_sha256']}:facebook:publish",'permalink':None}},
            'tiktok':{'publication':{'state':'unknown','operation_id':'ttop',
                'idempotency_key':f"thoremix:{old['source_sha256']}:tiktok:publish",'permalink':None}},
            'youtube':{'publication':{'state':'confirmed','operation_id':'ytop',
                'idempotency_key':f"thoremix:{old['source_sha256']}:youtube:publish",
                'permalink':'https://youtube.com/shorts/demo'},
                'comment':{'state':'unknown','operation_id':'ytcomment',
                'idempotency_key':f"thoremix:{old['source_sha256']}:youtube:comment",'permalink':None}}
        }}
    atomic_json(folder/'publication.json',publication)

    repair_dir=settings.data/'audio-repairs'/job['id']
    render=repair_dir/'render'; render.mkdir(parents=True)
    candidate_copy=render/'candidate.mp4'; candidate_copy.write_bytes(candidate.read_bytes())
    candidate_sha=sha256(candidate_copy)
    repair={'state':'candidate_ready_revision_required','job_id':job['id'],
        'package_sha256_before':current_sha,'video_sha256_before':old['video_sha256'],
        'native_sha256':native_sha,'candidate_path':str(candidate_copy),
        'candidate_sha256':candidate_sha,'audio_guard':{'preserved':True},
        'finishing':{'video_sha256':candidate_sha,'base_sha256':native_sha,
                     'audio_guard':{'preserved':True},'media':{'full_decode':True}}}
    atomic_json(repair_dir/'repair.json',repair)

    journal=settings.data/'krp'/'state.sqlite3'; journal.parent.mkdir(parents=True)
    with sqlite3.connect(journal) as db:
        db.execute('''CREATE TABLE effects(
            operation_id TEXT PRIMARY KEY,idempotency_key TEXT,action TEXT,platform TEXT,
            actor TEXT,profile TEXT,asset_sha256 TEXT,payload_sha256 TEXT,payload_json TEXT,
            state TEXT,permalink TEXT,external_id TEXT,reason TEXT,evidence_json TEXT,
            attempts INTEGER,created_at TEXT,updated_at TEXT)''')
        def insert(op,key,action,platform,state,asset,permalink=None,evidence=None):
            payload={'extra':{'package_sha256':publication_sha}}
            db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
                op,key,action,platform,'thoremix',settings.social_profile,asset,'c'*64,
                json.dumps(payload),state,permalink,None,None,json.dumps(evidence or {}),
                1,'2026-09-28T00:00:00+00:00','2026-09-28T00:00:00+00:00'))
        for platform,op in (('facebook','fbop'),('tiktok','ttop')):
            receipt_dir=settings.data/'krp'/'artifacts'/op; receipt_dir.mkdir(parents=True)
            receipt=receipt_dir/f'{platform}-needs_input.json'
            atomic_json(receipt,{'operation_id':op,'platform':platform,'action':'publish_reel',
                'actor':'thoremix','profile':settings.social_profile,'payload_sha256':'c'*64,
                'asset_sha256':old['video_sha256'],'stage':'needs_input','state':'needs_input',
                'submit_may_have_happened':False,'permalink':None,'external_id':None})
            insert(op,publication['platforms'][platform]['publication']['idempotency_key'],
                   'publish_reel',platform,'needs_input',old['video_sha256'],
                   evidence={'receipts':{'needs_input':str(receipt)}})
        insert('ytop',publication['platforms']['youtube']['publication']['idempotency_key'],
               'publish_reel','youtube','confirmed',old['video_sha256'],
               permalink='https://youtube.com/shorts/demo')
        insert('ytcomment',publication['platforms']['youtube']['comment']['idempotency_key'],
               'create_comment','youtube','needs_input',None)

    return mod,settings,campaign,job,folder,package_path,old,repair_dir/'repair.json',candidate_sha,journal


def test_prepare_clean_media_correction_preserves_old_and_retains_youtube(correction_case):
    mod,settings,campaign,job,old_dir,package_path,old,repair_path,candidate_sha,journal=correction_case
    old_files={str(p.relative_to(old_dir)):p.read_bytes() for p in old_dir.rglob('*') if p.is_file()}
    before_journal=journal.read_bytes()

    result=mod.prepare_media_correction(settings,job['id'])

    assert result['state']=='correction_ready'
    assert result['video_sha256']==candidate_sha
    assert result['publication_targets']==['facebook','tiktok']
    assert result['idempotency_namespace'].endswith(':revision:'+candidate_sha)
    assert result['retained_publications']['youtube']['state']=='retained'
    assert result['retained_publications']['youtube']['permalink']=='https://youtube.com/shorts/demo'
    assert journal.read_bytes()==before_journal

    current=campaign.get(job['id'])
    assert current['state']=='video_ready'
    target=Path(current['package_dir'])
    assert target!=old_dir and target.name.endswith('-correction-'+candidate_sha[:12])
    assert not (target/'publication.json').exists()
    package=json.loads((target/'package.json').read_text(encoding='utf-8'))
    assert package['publication_revision']==candidate_sha
    assert package['publication_targets']==['facebook','tiktok']
    assert package['supersedes_package_sha256']==result['prior_package_sha256']
    assert package['prior_publication_package_sha256']=='b'*64
    assert package['qa']['native_audio_preserved'] is True
    assert package['qa']['decoded_audio_all_zero'] is False
    assert len(package['frames'])==4
    assert all(Path(row['path']).is_file() for row in package['frames'])
    assert package['retained_publications']['youtube']['operation_id']=='ytop'
    assert package['retained_publications']['youtube']['comment']['operation_id']=='ytcomment'
    assert {str(p.relative_to(old_dir)):p.read_bytes() for p in old_dir.rglob('*') if p.is_file()}==old_files


@pytest.mark.parametrize('case', ['facebook_not_proven','youtube_not_confirmed','repair_not_preserved','candidate_changed'])
def test_correction_fails_closed_without_complete_evidence(correction_case,case):
    mod,settings,campaign,job,old_dir,package_path,old,repair_path,candidate_sha,journal=correction_case
    if case in {'facebook_not_proven','youtube_not_confirmed'}:
        with sqlite3.connect(journal) as db:
            op='fbop' if case=='facebook_not_proven' else 'ytop'
            db.execute('UPDATE effects SET state=? WHERE operation_id=?',
                       ('unknown' if case=='facebook_not_proven' else 'needs_input',op))
    elif case=='repair_not_preserved':
        value=json.loads(repair_path.read_text(encoding='utf-8'))
        value['audio_guard']['preserved']=False
        atomic_json(repair_path,value)
    else:
        value=json.loads(repair_path.read_text(encoding='utf-8'))
        Path(value['candidate_path']).write_bytes(b'tampered')

    before=campaign.get(job['id'])
    with pytest.raises(ValueError):
        mod.prepare_media_correction(settings,job['id'])
    assert campaign.get(job['id'])==before
    assert not list(settings.output.glob('*-correction-*'))


def test_revision_package_is_publishable_but_uses_only_new_targets(correction_case):
    mod,settings,campaign,job,*_=correction_case
    result=mod.prepare_media_correction(settings,job['id'])
    from agent.thoremix.publishing import _manifest
    manifest,digest=_manifest(Path(result['package']).parent)
    assert manifest['publication_targets']==['facebook','tiktok']
    assert manifest['publication_revision']==result['video_sha256']
    assert manifest['owner_correction']
    assert digest==result['package_sha256']
