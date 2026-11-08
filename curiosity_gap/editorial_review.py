"""Independent *structural* audit and a blank, blinded editor review set.

This never invents editor scores or calls an AI model. It uses the exact same
observability checks across A/B/C regardless of their selection score.
"""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path


def common_rubric(c):
    """Facts from existing source-grounded annotations; NOT human quality ratings."""
    l=c['ledger']; op=l['opening_first_3_seconds']; end=l['final_cut']
    risk=l.get('editorial_risks',{})
    seg=c['segments'][0]
    return {
        'duration_20_to_60':20<=c['duration']<=60,
        'first_three_second_hook_timing_proved':not op['hook_timing_uncertain'],
        'retrospective_opening_not_flagged':not risk.get('retrospective_opening_possible',False),
        'opening_question_not_immediately_answered':not risk.get('opening_question_answered_soon',False),
        'explicit_or_consequence_ending':end['question_type'] in ('explicit_question','inferred_consequence'),
        'context_switch_not_flagged':not l['comprehension']['major_context_switch_possible'],
        'no_dialogue_continuation_warning':not any('Opening dialogue begins as a continuation' in x for x in c['warnings']),
        'cut_has_nonempty_evidence':bool(op['evidence_ids'] and end['evidence_ids']),
        'source_segment':[seg['start_stamp'],seg['end_stamp']]
    }


def shared_measure_comparison(result):
    """Same audit questions applied to all three output sets (no method-specific weights)."""
    fields=[k for k in common_rubric(next(iter(result['outputs']['A']))).keys() if k!='source_segment'] if result['outputs']['A'] else []
    comparison={}
    for method,cards in result['outputs'].items():
        rows=[common_rubric(c) for c in cards]
        comparison[method]={
            'sample_size':len(cards),
            'rates':{k:round(sum(bool(r[k]) for r in rows)/len(rows),3) if rows else None for k in fields},
            'cases':[{'episode':c['episode'],'segments':r['source_segment'], **{k:r[k] for k in fields}} for c,r in zip(cards,rows)]
        }
    return {'basis':'Common structural questions applied to different method-selected clips. Not human/editor or audience performance.',
            'evaluation_design':'Selections not matched; some criteria also influence C selection, so results are descriptive and selection-biased.',
            'methods':comparison}


def export_blinded_review(result,pack,out,per_method=4):
    """Create a source-only review worksheet with the methods hidden until review.

    The answer key is saved separately. All files are PRIVATE because they cite Kuku scripts.
    """
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    selections={}
    for method in ('A','B','C'):
        for c in result['outputs'][method][:per_method]:
            s=c['segments'][0]
            key=(c['episode'],s['start'],s['end'])
            selections.setdefault(key,set()).add(method)
    records=[]
    for (ep,lo,hi),methods in selections.items():
        stable=hashlib.sha256(f'{ep}|{lo:.3f}|{hi:.3f}'.encode()).hexdigest()[:10].upper()
        records.append({'anonymous_id':'REVIEW-'+stable,'episode':ep,'start_seconds':lo,'end_seconds':hi,'methods':sorted(methods)})
    records.sort(key=lambda r:r['anonymous_id'])  # Deterministic blind order; no rank/method information.
    columns=['anonymous_id','episode','start_seconds','end_seconds',
             'hook_0_to_5','standalone_clarity_0_to_5','unresolved_curiosity_0_to_5',
             'boundary_quality_0_to_5','would_post_yes_no','editor_notes']
    with (out/'15_blinded_editor_scoring_BLANK_PRIVATE.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,columns);w.writeheader()
        for r in records:w.writerow({k:r.get(k,'') for k in columns})
    with (out/'17_reviewer_unblinding_key_KEEP_SEPARATE_PRIVATE.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,['anonymous_id','method_sources']);w.writeheader()
        for r in records:w.writerow({'anonymous_id':r['anonymous_id'],'method_sources':' / '.join(r['methods'])})
    lookup={e['episode']:e for e in pack['episodes']}
    source_lines=['# Private blinded editorial review excerpts','',
                  'This is a blank review exercise. Method labels and scores are withheld. Use video if available; otherwise mark visual hooks as unverified.','',
                  'Reviewer instructions: score hook, clarity, unresolved curiosity, boundary feasibility (0–5) independently. Do not open the answer key until scoring is complete.','']
    for r in records:
        s,e=r['start_seconds'],r['end_seconds']
        source_lines += [f"## {r['anonymous_id']} · Episode {r['episode']} · {s:.2f}–{e:.2f} seconds",'']
        for ev in lookup[r['episode']]['events']:
            if ev['kind'] not in ('dialogue','action'):continue
            if ev['start']>=s-.001 and ev['end']<=e+.001 and ev['end']>s:
                txt=ev['text'].replace('\n',' ').strip()
                source_lines.append(f"- {ev['start']:.2f}–{ev['end']:.2f} [{ev['id']}] {ev['speaker'] or ev['kind']}: {txt}")
        source_lines.append('')
    (out/'16_blinded_editor_evidence_PRIVATE.md').write_text('\n'.join(source_lines),encoding='utf-8')
    manifest={'clips_for_review':len(records),'method_shortlist_limit':per_method,'scores_filled':False,
              'reviewer_status':'Not performed; worksheet is blank',
              'blind_procedure':'Methods hidden in scoring and evidence files; separate sealed mapping file.',
              'warning':'Source screenplay text is proprietary. Never publish these review files.'}
    (out/'18_review_design_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest
