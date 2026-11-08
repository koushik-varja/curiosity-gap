import io,json,os,zipfile
import pytest
from curiosity_gap.parser import parse_episode,parse_zip,stamp,to_seconds
from curiosity_gap.engine import run,generate_candidates,validate_output,metrics,evaluate_clip,overlap_ratio,ledger_for_clip,opening_visibility
from curiosity_gap.adapters import isolated_payload,validate_assessment,ModelError,OpenAICompatibleAdapter,run_optional_model
from curiosity_gap.cli import export
from pathlib import Path

EXAMPLE=Path(__file__).resolve().parents[1]/'examples'/'synthetic_episode.txt'

@pytest.fixture
def synthetic():return parse_episode(EXAMPLE.read_text(),EXAMPLE.name)

@pytest.fixture
def pack(synthetic):return {'episodes':[synthetic],'files_found':1,'errors':[]}

def test_clock_precision():
    assert to_seconds('02:18.25')==138.25
    assert stamp(138.25)=='02:18.25'

def test_invalid_clock():
    with pytest.raises(ValueError):to_seconds('00:69.50')
    with pytest.raises(ValueError):to_seconds('invalid')

def test_parse_scenes_events(synthetic):
    assert len(synthetic['scenes'])==1 and len(synthetic['events'])>=10
    assert synthetic['events'][1]['kind']=='dialogue'

def test_source_provenance(synthetic):
    e=synthetic['events'][0]
    assert e['source']['filename']=='synthetic_episode.txt'
    assert e['source']['line']>0
    assert e['id'].startswith('E001-V')

def test_uppercase_scene_metadata():
    s=EXAMPLE.read_text().replace('Scene heading:','SCENE HEADING:').replace('Scene start:','SCENE START:').replace('Scene end:','SCENE END:')
    p=parse_episode(s,'episode-001.txt')
    assert p['scenes'][0]['start']==0 and p['scenes'][0]['end']==83

def test_missing_metadata_fallback():
    s=EXAMPLE.read_text().replace('EPISODE NUMBER: Episode 1','')
    e=parse_episode(s,'episode-004.txt',fallback_number=4)
    assert e['episode']==4 and e['warnings']

def test_malformed_scene_warning():
    s=EXAMPLE.read_text().replace('Scene end: 01:23.00','Scene end: ???')
    assert any('missing start/end' in x for x in parse_episode(s,'e.txt')['warnings'])

def test_unrecognized_event_warning():
    s=EXAMPLE.read_text()+ '\n**ACTION:**\nStart: (invalid) | End: (00:22.00)\nMissing time\n'
    assert any('unrecognized' in x for x in parse_episode(s,'e.txt')['warnings'])

def test_invalid_event_boundary_warning():
    s=EXAMPLE.read_text().replace('Start: (00:00.00) | End: (00:03.00)','Start: (00:04.00) | End: (00:03.00)',1)
    assert any('invalid boundaries' in x for x in parse_episode(s,'e.txt')['warnings'])

def test_overlap_is_legitimate(synthetic):
    assert not any('overlap' in x for x in synthetic['warnings'])

def test_zip_extraction(synthetic):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:z.writestr('episode-001.txt',EXAMPLE.read_bytes())
    parsed=parse_zip(io.BytesIO(buf.getvalue()))
    assert parsed['files_found']==1 and len(parsed['episodes'])==1

def test_zip_graceful_bad_input():
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:z.writestr('episode-001.txt',b'\xff\xfe')
    p=parse_zip(io.BytesIO(buf.getvalue()))
    assert len(p['errors'])==1 and not p['episodes']

def test_candidate_source_bounds(synthetic):
    a=generate_candidates(synthetic)
    assert a
    assert all(20<=x['duration']<=60 and x['segments'][0]['end']<=synthetic['duration'] for x in a)

def test_no_split_dialogue(synthetic):
    p=evaluate_clip(synthetic, 1.0,42.,'C')
    assert p is None  # first dialogue began at 0.25

def test_ledger_source_only(synthetic):
    a=generate_candidates(synthetic)[0]
    led=a['ledger']
    assert led['opening_first_3_seconds']['lead_event_id'] is not None
    assert led['final_cut']['viewer_question']
    assert all(i.startswith('E001') for i in a['evidence_event_ids'])

def test_context_isolation(synthetic):
    c=generate_candidates(synthetic)[0]
    payload=isolated_payload(synthetic,c)
    serial=json.dumps(payload)
    assert 'EPISODE LOGLINE' not in serial and 'continuity' not in serial and 'logline' not in serial
    assert all(e['end']>c['segments'][0]['start'] and e['start']<c['segments'][0]['end'] for e in payload['events'])

def test_model_validation(synthetic):
    c=generate_candidates(synthetic)[0];payload=isolated_payload(synthetic,c)
    opening=next((e['id'] for e in payload['events'] if e['start']<payload['clip_start']+3 and e['end']>payload['clip_start']),None)
    ending=next((e['id'] for e in payload['events'] if e['start']<payload['clip_end'] and e['end']>payload['clip_end']-5),None)
    a={'hook_strength':5,'standalone_comprehension':5,'unresolved_curiosity':5,'quality_warnings':[],'hook_evidence_id':opening,'cliff_evidence_id':ending,'reason':'In-clip conflict and unresolved consequence','unanswered_question':'Who caused the trouble in this clip?'}
    assert validate_assessment(a,payload)
    a['hook_evidence_id']='MADE-UP'
    with pytest.raises(ModelError):validate_assessment(a,payload)

def test_model_missing_credentials(monkeypatch):
    monkeypatch.delenv('CG_API_KEY',raising=False);monkeypatch.delenv('CG_MODEL',raising=False)
    with pytest.raises(ModelError):OpenAICompatibleAdapter()

def test_full_offline_run(pack):
    result=run(pack,final_count=5,minimum_score=0)
    assert result['summary']['episodes_processed']==1
    assert result['summary']['model_calls']==0
    assert result['summary']['candidate_windows_generated_and_evaluated']>0
    assert validate_output(pack,result)['passed']

def test_dedup_overlap():
    a={'segments':[{'episode':1,'start':0,'end':40}]}
    b={'segments':[{'episode':1,'start':5,'end':45}]}
    c={'segments':[{'episode':2,'start':5,'end':45}]}
    assert overlap_ratio(a,b)>.6 and overlap_ratio(a,c)==0

def test_three_way_output(pack):
    result=run(pack,minimum_score=0)
    assert set(result['outputs'])=={'A','B','C'}
    assert metrics(pack,result)['method_metrics']['C']['n']>0

def test_exports(tmp_path,pack):
    result=run(pack,minimum_score=0)
    validation,comparison=export(pack,result,tmp_path)
    assert validation['passed']
    assert (tmp_path/'07_ranked_promos_PRIVATE.json').exists()
    assert (tmp_path/'ranked_editorial_cards_PRIVATE.csv').exists()
    assert json.loads((tmp_path/'11_rejection_register_PRIVATE.json').read_text())['total_rejected']>=0
    assert json.loads((tmp_path/'00_run_manifest.json').read_text())['validation_passed']

def test_empty_pack():
    s=parse_episode('EPISODE NUMBER: Episode 19\n','episode-019.txt')
    assert s['warnings'] and s['events']==[]
    assert run({'episodes':[s],'files_found':1,'errors':[]})['summary']['final_C']==0

def test_private_full_pack_when_supplied():
    src=os.environ.get('CG_PRIVATE_PACK')
    if not src:pytest.skip('Set CG_PRIVATE_PACK to run proprietary full-pack integration test')
    pack=parse_zip(src);res=run(pack)
    assert pack['files_found']==50 and len(pack['episodes'])==50
    assert not pack['errors']
    assert validate_output(pack,res)['passed']
    assert sorted(e['episode'] for e in pack['episodes'])==list(range(1,51))


def test_opening_partial_event_marked_uncertain(synthetic):
    # Clip starts at a dialogue boundary; an action overlapping the 3-second window
    # cannot be quoted as if fully observed in that window.
    e={'id':'eventA','start':0,'end':8,'kind':'action','text':'A dramatic threat at the very end','speaker':'','scene_id':'S1'}
    assert opening_visibility(e,0,40)=='partially_overlaps_three_seconds'
    led=ledger_for_clip([e],0,40)
    assert led['opening_first_3_seconds']['hook_timing_uncertain']
    assert 'dramatic threat' not in led['opening_first_3_seconds']['seen_or_heard']


def test_partial_hook_cannot_receive_strong_rating(synthetic):
    ep=dict(synthetic)
    ep['events']=[dict(e) for e in synthetic['events']]
    ep['events']=[e for e in ep['events'] if e['start']>=3.1 or e['start']==0]
    for e in ep['events']:
        if e['start']==0:e['end']=9;e['kind']='action';e['text']='You are doomed!'
    c=evaluate_clip(ep,0,40,'C')
    if c:
        assert c['ledger']['opening_first_3_seconds']['hook_timing_uncertain']
        assert c['ratings']['hook']<=3


def test_partial_payload_does_not_leak_outside_clip():
    ep={'events':[{'id':'E001-V9999','kind':'action','speaker':'','start':0,'end':30,'text':'This is a spoiler from outside the selected clip.'}]}
    c={'segments':[{'start':5.,'end':25.}], 'duration':20.}
    payload=isolated_payload(ep,c)
    assert payload['events'][0]['partial_event']
    assert 'spoiler' not in str(payload)


def test_reject_unsupported_high_rating(synthetic):
    c=generate_candidates(synthetic)[0];payload=isolated_payload(synthetic,c)
    base={'hook_strength':10,'standalone_comprehension':10,'unresolved_curiosity':10,
          'reason':'An intense reveal introduces conflict','unanswered_question':'What will follow the dangerous threat?',
          'quality_warnings':[], 'hook_evidence_id':None, 'cliff_evidence_id':None}
    with pytest.raises(ModelError):validate_assessment(base,payload)
    b=dict(base,hook_strength=3,unresolved_curiosity=3)
    assert validate_assessment(b,payload)
    with pytest.raises(ModelError):validate_assessment(dict(b,reason=''),payload)
    with pytest.raises(ModelError):validate_assessment(dict(b,hook_evidence_id='unknown'),payload)
    with pytest.raises(ModelError):validate_assessment(dict(b,quality_warnings='none'),payload)


def test_reject_partial_event_strong_hook(synthetic):
    c=generate_candidates(synthetic)[0];payload=isolated_payload(synthetic,c)
    partial=next((e['id'] for e in payload['events'] if e['partial_event'] and e['start']<payload['clip_start']+3),None)
    if partial:
        a={'hook_strength':10,'standalone_comprehension':5,'unresolved_curiosity':2,
           'reason':'A difficult source boundary','unanswered_question':'Uncertain ending still needs review',
           'quality_warnings':['timing uncertain'], 'hook_evidence_id':partial,'cliff_evidence_id':None}
        with pytest.raises(ModelError):validate_assessment(a,payload)


def test_mock_model_changes_final_ranking(pack):
    results=run(pack,minimum_score=0)
    class FakeAdapter:
        model='mock';base_url='mock://offline'
        def complete(self,system,payload):
            op=next((e for e in payload['events'] if e['start']>=payload['clip_start']-.01 and e['end']<=payload['clip_start']+3+.01 and not e['partial_event']),None)
            cl=next((e for e in reversed(payload['events']) if e['end']<=payload['clip_end']+.01 and e['end']>payload['clip_end']-5 and not e['partial_event']),None)
            if not op or not cl:
                return {'raw_response':'{}','usage':{},'assessment':None}
            a={'hook_strength':7,'standalone_comprehension':6,'unresolved_curiosity':8,
               'reason':'Threat and response create tension in the supplied events',
               'unanswered_question':'Will the central conflict be resolved?',
               'quality_warnings':[],'hook_evidence_id':op['id'],'cliff_evidence_id':cl['id']}
            return {'raw_response':json.dumps(a),'usage':{'total_tokens':25},'assessment':a}
    ret=run_optional_model(pack,results,limit=8,adapter=FakeAdapter())
    assert ret['attempted']>=1
    assert ret['accepted']>0
    assert ret['ranked_model_promos']
    assert ret['ranked_model_promos'][0]['method']=='M'
    assert 'semantic_evaluation' in ret['ranked_model_promos'][0]
    assert all(a['payload_sha256'] and 'latency_seconds' in a for a in ret['attempts'])
    assert results['summary']['model_calls']==0  # no silent fallback override


def test_mock_model_failure_is_recorded(pack):
    class ErrorAdapter:
        model='broken';base_url='mock://broken'
        def complete(self,*args):raise ModelError('service unavailable')
    res=run_optional_model(pack,run(pack,minimum_score=0),limit=5,adapter=ErrorAdapter())
    assert res['attempted']>=1 and res['accepted']==0
    assert not res['ranked_model_promos']
    assert all(i['status']=='failed' for i in res['attempts'])


def test_cut_comparison_is_genuine(pack):
    res=run(pack,minimum_score=0)
    for r in res['outputs']['C']:
        cmp=r['cut_comparison']
        if not cmp:continue
        assert cmp['chosen']['segments']!=cmp['best_rejected']['segments']
        assert cmp['chosen']['score']==r['score']
        assert isinstance(cmp['opening_difference'],str)


def test_reproducible_full_run(pack):
    a=run(pack,minimum_score=0);b=run(pack,minimum_score=0)
    assert a['outputs']==b['outputs']
    assert len(a['candidates_C'])==len(b['candidates_C'])

def test_private_local_html_render(tmp_path,pack):
    from curiosity_gap.review_html import render_review
    res=run(pack,minimum_score=0)
    target=tmp_path/'private_review.html';render_review(res,target)
    html=target.read_text()
    assert '<!doctype html>' in html
    assert 'no external requests' in html
    assert '<script id="data"' in html
    assert 'episode-filter' in html
    assert 'https://' not in html

# v0.3 editorial-quality regression cases, derived from general rule behavior.
from curiosity_gap.editorial_review import common_rubric, shared_measure_comparison,export_blinded_review
from curiosity_gap.engine import editorial_risks

def test_retrospective_exposition_opening_weakens_hook(synthetic):
    ep=dict(synthetic)
    ep['events']=[dict(x) for x in synthetic['events']]
    first=next(x for x in ep['events'] if x['kind']=='dialogue')
    first['text']='While the kingdom mourned an heir.'
    res=evaluate_clip(ep,first['start'],first['start']+40,'C')
    if res:
        assert res['ledger']['editorial_risks']['retrospective_opening_possible']
        assert res['ratings']['hook']<4

def test_immediate_explicit_answer_is_flagged():
    a={'kind':'dialogue','id':'E111-V001','start':0,'end':2,'speaker':'P','text':'Do you think she will be executed?'}
    b={'kind':'dialogue','id':'E111-V002','start':3,'end':6,'speaker':'Q','text':'After the trial? Of course.'}
    risk=editorial_risks([a,b],0,30)
    assert risk['opening_question_answered_soon']
    assert risk['answer_evidence_ids']==['E111-V001','E111-V002']

def test_rhetorical_challenge_not_automatically_answered():
    a={'kind':'dialogue','id':'A','start':0,'end':2,'speaker':'P','text':'You think love makes you better than me?'}
    b={'kind':'dialogue','id':'B','start':2.5,'end':5,'speaker':'Q','text':'No, but cruelty does not make you better.'}
    assert not editorial_risks([a,b],0,30)['opening_question_answered_soon']

def test_generic_reassurance_not_strong_hook(synthetic):
    ep=dict(synthetic);ep['events']=[dict(x) for x in synthetic['events']]
    first=next(x for x in ep['events'] if x['kind']=='dialogue')
    first['text']='Rest now. You are safe tonight.'
    res=evaluate_clip(ep,first['start'],first['start']+40,'C')
    if res:
        assert res['ratings']['hook']<4
        assert any('generic reassurance' in w for w in res['warnings'])

def test_common_structural_metrics_same_schema(pack,tmp_path):
    r=run(pack)
    comparative=shared_measure_comparison(r)
    assert set(comparative['methods'])=={'A','B','C'}
    k=[set(v['rates']) for v in comparative['methods'].values()]
    assert k[0]==k[1]==k[2]
    report=export_blinded_review(r,pack,tmp_path,per_method=3)
    assert report['scores_filled'] is False
    assert (tmp_path/'15_blinded_editor_scoring_BLANK_PRIVATE.csv').exists()
    assert (tmp_path/'16_blinded_editor_evidence_PRIVATE.md').exists()
    content=(tmp_path/'15_blinded_editor_scoring_BLANK_PRIVATE.csv').read_text()
    assert 'method_sources' not in content
    assert 'hook_0_to_5' in content

def test_ending_reference_matches_ledger(synthetic):
    for c in generate_candidates(synthetic)[:12]:
        assert c['cliffhanger_event_id']==c['ledger']['final_cut']['lead_event_id']

def test_opening_object_reference_flag_is_general():
    a={'kind':'dialogue','id':'X','start':0,'end':2,'speaker':'P','text':'You cannot just destroy it!'}
    b={'kind':'dialogue','id':'Y','start':0,'end':2,'speaker':'P','text':'It is my home.'}
    assert editorial_risks([a],0,30)['unanchored_opening_object_possible']
    assert not editorial_risks([b],0,30)['unanchored_opening_object_possible']
