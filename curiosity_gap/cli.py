"""Run with python -m curiosity_gap.cli --input /path/to/scripts.zip --out private_outputs"""
from __future__ import annotations
import argparse,csv,hashlib,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
from .parser import parse_zip
from .engine import run,validate_output,metrics
from .review_html import render_review
from .editorial_review import shared_measure_comparison,export_blinded_review
from . import __version__


def dump(path,obj):
    with open(path,'w',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)


def export(pack,result,destination,mode='offline',model_result=None,source_hash=None):
    out=Path(destination);out.mkdir(parents=True,exist_ok=True)
    validation=validate_output(pack,result)
    comparison=metrics(pack,result)
    dump(out/'01_run_summary.json',result['summary'])
    dump(out/'02_episode_coverage.json',result['per_episode'])
    dump(out/'03_normalized_episodes_PRIVATE.json',pack['episodes'])
    dump(out/'04_candidates_C_raw_PRIVATE.json',result['candidates_C'])
    dump(out/'05_candidates_B_raw_PRIVATE.json',result['candidates_B'])
    dump(out/'06_baseline_A_raw_PRIVATE.json',result['candidates_A'])
    dump(out/'07_ranked_promos_PRIVATE.json',result['outputs'])
    dump(out/'08_validation_report.json',validation)
    dump(out/'09_comparison_proxy_metrics.json',comparison)
    dump(out/'14_common_structural_rubric_PRIVATE.json',shared_measure_comparison(result))
    export_blinded_review(result,pack,out)
    # Unedited comparison records from actual evaluated cuts, same screenplay evidence.
    paired=[]
    for card in result['outputs']['C']:
        cmp=card.get('cut_comparison')
        if cmp:
            paired.append({'promo_id':card['promo_id'],'episode':card['episode'],
               'chosen':cmp['chosen'],'rejected':cmp['best_rejected'],
               'opening_difference':cmp.get('opening_difference'),
               'ending_difference':cmp.get('ending_difference'),
               'score_warning':'Not an independent human or audience judgment'})
    dump(out/'13_paired_cut_structural_review_PRIVATE.json',{'paired_count':len(paired),'pairs':paired})
    # Keep an unedited machine-readable rejection register for full-pack coverage audits.
    selected=result['outputs']['C']
    selected_keys={(x['episode'],x['segments'][0]['start'],x['segments'][0]['end']) for x in selected}
    selected_episodes={x['episode'] for x in selected}
    rejected=[]
    for candidate in result['candidates_C']:
        seg=candidate['segments'][0]
        key=(candidate['episode'],seg['start'],seg['end'])
        if key in selected_keys:continue
        if candidate['score']<max(result['summary']['minimum_C_score'],5.65):reason='below_quality_threshold'
        elif candidate['ratings']['hook']<4:reason='three_second_hook_not_evidenced'
        elif candidate['ratings']['cliffhanger']<4.25:reason='weak_cliffhanger_proxy'
        elif candidate['ledger']['final_cut']['question_type'] not in ('explicit_question','inferred_consequence'):reason='unresolved_question_not_evidenced'
        elif candidate['ledger']['comprehension']['major_context_switch_possible']:reason='possible_context_switch'
        elif candidate['ledger']['editorial_risks']['retrospective_opening_possible']:reason='retrospective_opening_risk'
        elif candidate['ledger']['editorial_risks']['opening_question_answered_soon']:reason='opening_question_immediately_answered'
        elif any('Opening dialogue begins as a continuation' in w for w in candidate['warnings']):reason='opening_dialogue_continuation'
        elif candidate['episode'] in selected_episodes:reason='episode_portfolio_or_weaker_alternative'
        else:reason='outside_top_ranked_portfolio'
        rejected.append({'episode':candidate['episode'],'start':seg['start'],'end':seg['end'],'score':candidate['score'],'reason':reason,'warnings':candidate['warnings']})
    dump(out/'11_rejection_register_PRIVATE.json',{'total_rejected':len(rejected),'records':rejected,'note':'Machine selection reasons only. They are not human editorial rejections.'})
    if model_result is not None:
        dump(out/'10_optional_model_raw_PRIVATE.json',model_result)
        dump(out/'12_model_assisted_ranked_PRIVATE.json',model_result['ranked_model_promos'])
    with open(out/'ranked_editorial_cards_PRIVATE.csv','w',encoding='utf-8',newline='') as f:
        fields=['method','rank','promo_id','episode','start','end','duration','score','hook','cliffhanger','unanswered_viewer_question','warnings']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for method,recs in result['outputs'].items():
            for r in recs:
                s=r['segments'][0]
                writer.writerow({'method':method,'rank':r['rank'],'promo_id':r['promo_id'],'episode':r['episode'],'start':s['start_stamp'],'end':s['end_stamp'],'duration':r['duration'],'score':r['score'],'hook':r['hook'],'cliffhanger':r['cliffhanger'],'unanswered_viewer_question':r['unanswered_viewer_question'],'warnings':' | '.join(r['warnings'])})
    render_review(result,out/'PRIVATE_editor_review.html')
    run_manifest={'utc_created':datetime.now(timezone.utc).isoformat(),'version':__version__,'input_sha256':source_hash,'input_files':pack['files_found'],'pipeline_mode':mode,'validation_passed':validation['passed'],'model_status':('not used' if model_result is None else {'attempted':model_result['attempted'],'accepted':model_result['accepted']})}
    dump(out/'00_run_manifest.json',run_manifest)
    return validation,comparison


def main(argv=None):
    ap=argparse.ArgumentParser(description='Discover candidate screenplay promos with provenance and cut comparisons')
    ap.add_argument('--input',required=True,help='ZIP containing Kuku-style timestamped TXT scripts')
    ap.add_argument('--out',default='private_outputs',help='Output folder; contains proprietary-derived text: KEEP PRIVATE')
    ap.add_argument('--final-count',type=int,default=12)
    ap.add_argument('--min-score',type=float,default=5.3)
    ap.add_argument('--mode',choices=('offline','api'),default='offline',help='API mode is optional and requires CG_API_KEY, CG_MODEL')
    ap.add_argument('--max-model-evals',type=int,default=20)
    args=ap.parse_args(argv)
    try:
        with open(args.input,'rb') as f:sha=hashlib.sha256(f.read()).hexdigest()
        start=time.perf_counter()
        pack=parse_zip(args.input)
        if not pack['episodes']:raise RuntimeError('No parseable screenplay episodes found')
        result=run(pack,max(1,args.final_count),args.min_score)
        model_result=None
        if args.mode=='api':
            from .adapters import run_optional_model
            model_result=run_optional_model(pack,result,max(1,args.max_model_evals))
        validation,comparison=export(pack,result,args.out,mode=args.mode,model_result=model_result,source_hash=sha)
        print(json.dumps({'out':str(Path(args.out).resolve()),'seconds':round(time.perf_counter()-start,2),'summary':result['summary'],'validation':{'passed':validation['passed'],'violations':validation['violations']},'model_result':None if model_result is None else {'attempted':model_result['attempted'],'accepted':model_result['accepted']}},indent=2))
        return 0 if validation['passed'] and not pack['errors'] else 2
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}',file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
