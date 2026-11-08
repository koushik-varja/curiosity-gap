"""Transparent, reproducible offline promo discovery; creative scores are heuristic proxies.

Privacy rule: every evidence statement is derived from timed events inside the candidate.
The discovery stage may see the episode; the viewer stage NEVER sees metadata/loglines.
"""
from __future__ import annotations
from bisect import bisect_left
from collections import Counter
import hashlib, json, math, re
from .parser import stamp

# Not trained on or calibrated to real retention: these are explicit editorial heuristics.
PATTERNS={
 'revelation':r'\b(reveal|secret|truth|actually|real|rightful|identity|heir|duke|duchess|never knew|not who|you are|i am|it was|it is|the one who|you were|son|daughter)\b',
 'betrayal':r'\b(betray|liar|lied|deceiv|cheat|affair|marry|divorc|another woman|abandon|replace|stole|stolen|traitor)\b',
 'threat':r'\b(kill|die|dead|death|destroy|arrest|execute|prison|punish|never leave|never see|pay for|revenge|war|threat|blood|sword|knife|gun|guard|betrayed|hold you|take everything)\b',
 'reversal':r'\b(but|except|instead|yet|not anymore|however|wait|stop|no longer|not possible|impossible|suddenly|unexpected|who are you|how dare|too late)\b',
 'stakes':r'\b(mother|father|wife|husband|child|baby|sister|brother|family|love|marriage|wedding|inherit|estate|crown|king|duke|life|home|future)\b',
 'action':r'\b(slap|strik|hits?|punch|grab|collapse|fall|stagger|draws? (?:his |her )?sword|storms?|stabs?|shove|kneels?|gunshot|scream|gasp|blood|shatter|seiz|kisses?|door bursts|burst through)\b',
 'conflict':r'\b(why|how could|you cannot|you will not|never|refus|i won.t|you must|i demand|how dare|stop|choose|decide|prove|accus|threaten|shout|disbelief)\b',
 'resolution':r'\b(all is forgiven|i forgive you|everything is fine|we are safe|problem is solved|i understand now|i accept|we have won|it is over|we are together|the end)\b'
}
REGEX={k:re.compile(v,re.I) for k,v in PATTERNS.items()}
INTENSITY={'revelation':2.1,'betrayal':1.8,'threat':2.0,'reversal':1.45,'stakes':0.55,'action':1.85,'conflict':1.2}
KIND={'dialogue':1.0,'action':.72,'camera':.24,'sound':.08}


def event_signal(e):
    if '_signal' in e:return e['_signal']
    txt=e['text']; tags=[k for k,pat in REGEX.items() if pat.search(txt)]
    score=sum(INTENSITY.get(k,0) for k in tags)
    if '?' in txt:score+=1.25
    if '!' in txt:score+=.55
    if e['kind']=='dialogue':score+=.8
    elif e['kind']=='action':score+=.3
    if re.search(r'\b(cut to black|ominous cliffhanger)\b',txt,re.I):score-=1.5
    score=max(0., (score+KIND[e['kind']])*.85)
    e['_signal']=(round(min(score,10),4),tags)
    return e['_signal']


def _text(e):return e['text'].replace('\n',' ').strip().strip('"')

def _brief(e,n=145):
    if not e:return ''
    s=_text(e)
    return (s[:n-1]+'…') if len(s)>n else s


def _overlap(ev,lo,hi):return ev['start'] < hi-.0001 and ev['end'] > lo+.0001

def _in_window(events,lo,hi):return [e for e in events if _overlap(e,lo,hi)]

def _cut_issue(events,start,end):
    # A cut in the middle of an event's spoken sentence is materially awkward.
    opening=[e['id'] for e in events if e['kind']=='dialogue' and e['start'] < start-.01 and e['end'] > start+.01]
    closing=[e['id'] for e in events if e['kind']=='dialogue' and e['start'] < end-.01 and e['end'] > end+.01]
    return opening,closing


def opening_visibility(e, start, end):
    """Screenplay spans are *not* word- or frame-aligned observations."""
    lo, hi = start, min(start + 3.0, end)
    if not _overlap(e, lo, hi):
        return 'not_in_opening'
    if e['start'] < start - .01:
        return 'started_before_clip'
    if e['end'] <= hi + .01:
        return 'fully_within_three_seconds'
    return 'partially_overlaps_three_seconds'


def _speaker_switch(clipped, start, end):
    early = {e['speaker'] for e in clipped if e['kind'] == 'dialogue' and e['start'] < start + 13 and e['speaker']}
    late = {e['speaker'] for e in clipped if e['kind'] == 'dialogue' and e['end'] > end - 13 and e['speaker']}
    # A potential narrative shift, NOT proof of incoherence; avoid inferring it from one line.
    return bool(early and late and len(early | late) >= 3 and len(early & late)/len(early | late) <= .26 and len(late)>=2)


def editorial_risks(clipped, start, end):
    """Cautious, source-only diagnostics. Flags prompt editor review; not semantic truth."""
    early = sorted((e for e in clipped if e['kind']=='dialogue' and
                    e['start'] >= start-.01 and e['start'] < start+3.01),
                   key=lambda e:(e['start'], e['end']))
    first = early[0] if early else None
    text = _text(first) if first else ''
    unresolved_object_possible=bool(first and len(text.split())<=8 and
        re.search(r'\b(?:it|this|that|them)\b',text,re.I) and
        not re.search(r'\b(?:my|your|our|their)\s+[a-z]{3,}\b',text,re.I))
    past_context = bool(first and re.search(
        r'^(?:while|back then|years ago|once upon|in those days|when we|after the|before the)\b',
        text, re.I))
    # Introductory backstory is not necessarily a poor *video* hook; label the uncertainty.
    # Only direct subsequent answers of a different speaker count here.
    early_question_answered = False
    supporting = []
    if first and '?' in text and re.match(r'^(?:do you think|will|is|was|can|could|would|did|does|has|have|are|were)\b', text, re.I):
        follow = sorted((e for e in clipped if e['kind']=='dialogue' and
                         e['speaker'] != first['speaker'] and
                         first['end']-.01 <= e['start'] <= min(end, first['end']+9)),
                        key=lambda e:e['start'])
        if follow:
            response = _text(follow[0]).lstrip('"\' ').strip()
            early_question_answered=bool(re.match(
                r'^(?:yes\b|no\b|of course\b|certainly\b|absolutely\b|indeed\b|never\b|not at all\b)',
                response, re.I) or (len(response.split())<=16 and re.search(r'\b(?:of course|absolutely|certainly)\b',response,re.I)))
            if early_question_answered:supporting=[first['id'],follow[0]['id']]
    return {'retrospective_opening_possible':past_context,
            'unanchored_opening_object_possible':unresolved_object_possible,
            'opening_question_answered_soon':early_question_answered,
            'opening_evidence_id':first['id'] if first else None,
            'answer_evidence_ids':supporting,
            'interpretation':'Mechanical editorial risk flags; verify all questions and pacing in footage.'}


def ledger_for_clip(clipped,start,end):
    """Only clip-contained evidence, with explicit uncertainty about intra-event timing."""
    opener=[e for e in clipped if _overlap(e,start,min(start+3,end))]
    fully=[e for e in opener if opening_visibility(e,start,end)=='fully_within_three_seconds']
    opening_pool=fully if fully else opener
    open_sorted=sorted(opening_pool,key=lambda e:(-event_signal(e)[0],e['start'],e['id']))
    opener_e=open_sorted[0] if open_sorted else None
    ending=[e for e in clipped if _overlap(e,max(start,end-5),end)]
    fully_end=[e for e in ending if e['end']<=end+.01 and e['start']>=start-.01]
    ending_pool=[e for e in (fully_end if fully_end else ending) if e['kind'] in ('dialogue','action')]
    if not ending_pool:ending_pool=fully_end if fully_end else ending
    close_sorted=sorted(ending_pool,key=lambda e:(-e['end'],e['kind']!='dialogue',-end_value(e),e['id']))
    ending_e=close_sorted[0] if close_sorted else None
    speaks=[e for e in clipped if e['kind']=='dialogue']
    conflicts=[e for e in clipped if {'conflict','betrayal','threat'}.intersection(event_signal(e)[1])]
    stakes=[e for e in clipped if {'stakes','threat'}.intersection(event_signal(e)[1])]
    signaled_questions=[e for e in ending if '?' in e['text'] and e['kind']=='dialogue' and e['end']<=end+.01]
    # A late explicit question is not automatically unresolved: flag a subsequent response.
    q=signaled_questions[-1] if signaled_questions else ending_e
    later_answers=bool(q and any(e['kind']=='dialogue' and e['id']!=q['id'] and e['start']>=q['end']-.01 and e['start']<end-.01 for e in clipped))
    switch=_speaker_switch(clipped,start,end)
    qtags=event_signal(q)[1] if q else []
    forward_risk=bool(q and ('threat' in qtags or 'action' in qtags or re.search(r'\b(unless|if you|or else|will you|must decide|choose|before i|confess|poison|condemn|accus|dont|don.t|stop)\b',q['text'],re.I)))
    rhetorical=bool(q and re.search(r'\b(how dare you|what a joke|what is wrong with you|you truly mean it|why do you look at me like that)\b',q['text'],re.I))
    generic_question=bool(q and '?' in q['text'] and len(_text(q).split())<=4 and not ({'threat','action'}.intersection(qtags)))
    retrospective=bool(q and '?' not in q['text'] and re.search(r'\b(was|were|had|mourned|declared|back then|once|years ago)\b',q['text'],re.I) and not re.search(r'\b(will|soon|going to|next|must|before|now .*will)\b',q['text'],re.I))
    if q and '?' in q['text'] and not later_answers and not rhetorical and not generic_question and not switch:
        question='Explicit unanswered line in clip: '+_brief(q,100)
        qtype='explicit_question'
    elif q and retrospective and not later_answers:
        question='Retrospective exposition; future consequence is not established by final event.'
        qtype='retrospective_exposition'
    elif q and generic_question and not later_answers:
        question='Short context-dependent question; stakes are not established by the last line alone.'
        qtype='context_dependent_question'
    elif q and forward_risk and not later_answers and not switch:
        question='Potential unresolved consequence from the final event: '+_brief(q,85)
        qtype='inferred_consequence'
    elif switch:
        question='Ending may switch to different characters; central unresolved question is uncertain.'
        qtype='context_switch_uncertain'
    elif later_answers:
        question='Question is followed by dialogue before the cut; unresolved status uncertain.'
        qtype='possibly_resolved'
    else:
        question='No clearly evidenced unresolved question at cut.'
        qtype='unclear'
    named_speakers=sorted({e['speaker'] for e in speaks if e['speaker'] and len(e['speaker'])>1})
    open_q=[e for e in speaks if e['start']<start+10 and re.search(r'^[\"\']?(?:he|she|they|him|her|it|that|those|this)\b',_text(e),re.I)]
    lead_visibility=opening_visibility(opener_e,start,end) if opener_e else 'not_in_opening'
    observed=(_brief(opener_e) if opener_e and lead_visibility=='fully_within_three_seconds'
              else 'Text spans the first three seconds but its precise spoken/visual timing is unknown.' if opener_e
              else 'No timed event in the opening.')
    uncertain=lead_visibility!='fully_within_three_seconds'
    return {
      'opening_first_3_seconds':{'evidence_ids':[e['id'] for e in opener],
         'events':[{'id':e['id'],'visibility':opening_visibility(e,start,end)} for e in opener],
         'lead_event_id':opener_e['id'] if opener_e else None,
         'seen_or_heard':observed, 'hook_type_tags':event_signal(opener_e)[1] if opener_e else [],
         'hook_timing_uncertain':uncertain,'hook_timing_reason':('Precise intra-event word/shot timing is unavailable.' if uncertain else 'Entire timed event is within opening window.'),
         'weak_hook_flag':not opener_e or event_signal(opener_e)[0]<2.0},
      'comprehension':{'speakers_heard':named_speakers[:9],
         'conflict_evidence_ids':[e['id'] for e in sorted(conflicts,key=lambda e:-event_signal(e)[0])[:3]],
         'stakes_evidence_ids':[e['id'] for e in sorted(stakes,key=lambda e:-event_signal(e)[0])[:3]],
         'potential_unexplained_reference_ids':[e['id'] for e in open_q[:3]],
         'major_context_switch_possible':switch,
         'character_relationships':'unknown without semantic/footage review',
         'main_conflict':'not independently established; use cited in-clip evidence',
         'emotional_stakes':'not independently established; use cited in-clip evidence',
         'essential_missing_context':'unknown; human/editor or semantic model review required'},
      'final_cut':{'evidence_ids':[e['id'] for e in ending],
         'lead_event_id':ending_e['id'] if ending_e else None,
         'final_event_excerpt':_brief(ending_e) if ending_e and ending_e['end']<=end+.01 else 'Final event partially observed; exact cutoff unknown',
         'viewer_question':question,'question_type':qtype,
         'question_source_id':q['id'] if q else None,
         'question_resolved':True if later_answers else 'unknown',
         'external_context_required':'unknown',
         'confidence_explanation':'Mechanical question/consequence detection; storyline coherence requires editor or model review.'}
    }


def end_value(e):
    sig,tags=event_signal(e)
    txt=e['text']
    # Question or forward-looking peril is often a stronger cut than a resolution or a black frame.
    v=sig*.54+ ('?' in txt)*1.9+('threat' in tags)*1.0+('revelation' in tags)*.75+('reversal' in tags)*.4
    if 'resolution' in tags:v-=3.0
    if re.search(r'cut to black|fade out|cliffhanger',txt,re.I):v-=1.6
    if e['kind']=='camera':v*=.45
    if e['kind']=='sound':v*=.30
    return v


def evaluate_clip(episode,start,end,method='C'):
    """Deterministic score; 'C' adds context-blind ledger and caution checks."""
    events=_in_window(episode['events'],start,end)
    if not 20-.0001 <= end-start <= 60+.0001 or not events:return None
    before,after=_cut_issue(episode['events'],start,end)
    if before or after:return None  # avoid dialogue-splicing even in baseline
    opening=_in_window(events,start,min(end,start+3))
    last=_in_window(events,max(start,end-5),end)
    whole_open=[e for e in opening if opening_visibility(e,start,end)=='fully_within_three_seconds']
    hs=sorted(whole_open if whole_open else opening,key=lambda e:-event_signal(e)[0]);h=hs[0] if hs else None
    valid_last=[e for e in last if e['kind'] in ('dialogue','action') and e['end']<=end+.01]
    es=sorted(valid_last if valid_last else last,key=lambda e:(-e['end'],e['kind']!='dialogue',-end_value(e),e['id']));c=es[0] if es else None
    hook=min(10., (event_signal(h)[0] if h else 0.) *1.5)
    hook_timing_uncertain=not h or opening_visibility(h,start,end)!='fully_within_three_seconds'
    if hook_timing_uncertain:hook=min(hook,3.0)  # no full-line attribution to a partial event
    short_generic_hook=bool(h and h['kind']=='dialogue' and len(_text(h).split())<=3 and len(event_signal(h)[1])<=1)
    if short_generic_hook:hook=max(0.,hook-2.6)
    if h and re.search(r'^(?:\W*\b(?:but|because|and|so|then)\b|\.{2,})',_text(h),re.I):hook=min(hook,3.5)
    # Generic reassurance and mundane prompts are weak standalone acquisition hooks.
    # Apply the rule to language patterns, never to specific episode identifiers.
    low_stakes_opener=bool(h and (
        re.search(r'^(?:rest (?:now|easy)|calm down|don.t worry|be calm)\b',_text(h),re.I) or
        re.search(r'\b(?:you are|we are|everything is|it is) (?:safe|fine|okay|alright)\b',_text(h),re.I) or
        re.search(r'^why are you (?:walking|looking|talking|acting|standing|sitting)\b',_text(h),re.I)))
    if low_stakes_opener:hook=min(hook,3.4)
    cliff=min(10., max(0.,end_value(c) if c else 0.)*1.30)
    dialogue=[e for e in events if e['kind']=='dialogue']
    significant=[e for e in dialogue if event_signal(e)[0] >=2.5]
    tension=min(10.,sum(sorted((event_signal(e)[0] for e in significant),reverse=True)[:5])*.43)
    # Deterministic proxy for intelligibility, never call it viewer-rated comprehension.
    speakers={e['speaker'] for e in dialogue if e['speaker']}
    long = sum(len(_text(e).split()) for e in dialogue)
    pronouns=sum(bool(re.search(r'\b(?:he|she|it|them|they|this|that)\b',_text(e),re.I)) for e in dialogue[:5])
    named_support=min(1.0,len(speakers)*.5)
    arc=bool(significant and len(dialogue)>=3)
    comprehension=max(0,min(10., 2.8+named_support+1.7*arc+.028*min(long,75)-min(2.,pronouns*.34)-max(0,len(speakers)-2)*.60))
    if len(dialogue)<2:comprehension=min(comprehension,3.5)
    feasibility=10.0  # cut validity is a hard gate; no weak scoring of invalid cuts
    ledger=ledger_for_clip(events,start,end)
    editorial=editorial_risks(events,start,end)
    ledger['editorial_risks']=editorial
    if editorial['retrospective_opening_possible']:hook=min(hook,3.6)
    if editorial['opening_question_answered_soon']:hook=min(hook,3.7)
    question=ledger['final_cut']['question_type']
    if question!='explicit_question' and question!='inferred_consequence':cliff=min(cliff,2.1)
    if c and c['end']<end-1.1:cliff=max(0.,cliff-1.1)
    resolved=[e for e in events if REGEX['resolution'].search(e['text'])]
    if resolved and any(e['end']>end-10 for e in resolved):cliff=max(0,cliff-2.)
    # Stop mid-utterance or across unrelated scenes? Context-blind structural caution.
    first_dialogue=dialogue[0] if dialogue else None
    begins_continuation=bool(first_dialogue and (re.match(r'^[\"\']?(?:\.{2,}|but\b|and\b|because\b)',_text(first_dialogue),re.I) or _text(first_dialogue).startswith('...')))
    crosses_scenes=len({e['scene_id'] for e in events})>1
    if begins_continuation:comprehension=max(0.,comprehension-1.5)
    if crosses_scenes:comprehension=max(0.,comprehension-1.0)
    if ledger['comprehension']['major_context_switch_possible']:comprehension=max(0.,comprehension-2.0)
    if editorial['unanchored_opening_object_possible']:comprehension=max(0.,comprehension-.7)
    if method=='B':score=.42*hook+.39*cliff+.14*tension+.05*feasibility
    elif method=='A':score=.42*hook+.39*cliff+.14*tension+.05*feasibility
    else:score=.30*hook+.29*cliff+.25*comprehension+.11*tension+.05*feasibility
    warnings=[]
    if hook<4:warnings.append('Opening lacks strong three-second evidence (heuristic).')
    if hook_timing_uncertain:warnings.append('Opening event only partially visible in first 3 seconds; cannot claim entire hook arrives on time.')
    if short_generic_hook:warnings.append('Opening is a very short, potentially context-dependent utterance.')
    if low_stakes_opener:warnings.append('Opening is generic reassurance or mundane inquiry; initial dramatic stakes are uncertain.')
    if editorial['retrospective_opening_possible']:warnings.append('Opening is potentially retrospective backstory, not immediate action; verify acquisition hook.')
    if editorial['opening_question_answered_soon']:warnings.append('Opening question receives a direct response shortly afterward; sustained curiosity uncertain.')
    if editorial['unanchored_opening_object_possible']:warnings.append('Opening relies on an object pronoun without a proven preceding referent; check standalone clarity.')
    if cliff<4:warnings.append('Weak or unproven cliffhanger.')
    if comprehension<5:warnings.append('Standalone comprehension uncertain.')
    if question not in ('explicit_question','inferred_consequence'):warnings.append('Strong unresolved ending not evidenced; question or narrative thread may be resolved/unclear.')
    if ledger['comprehension']['major_context_switch_possible']:warnings.append('Possible abrupt speaker/context shift between opening and ending.')
    if len(speakers)>=4:warnings.append('Four or more speaking roles may overwhelm a new viewer.')
    if begins_continuation:warnings.append('Opening dialogue begins as a continuation; missing context possible.')
    if crosses_scenes:warnings.append('Clip crosses a scene boundary; check narrative continuity.')
    if any(e['start']<start-.01 and e['end']>start+.01 for e in events if e['kind']=='action'):warnings.append('Opening overlaps an action; visual start needs editor review.')
    if any(e['start']<end-.01 and e['end']>end+.01 for e in events if e['kind']=='action'):warnings.append('End overlaps an action; editor must check physical edit.')
    # A cautious adversarial pass, based only on events in this clip.
    if method=='C' and question not in ('explicit_question','inferred_consequence'):score-=1.15
    if method=='C' and hook_timing_uncertain:score-=.45
    if method=='C' and ledger['comprehension']['major_context_switch_possible']:score-=.85
    if method=='C' and begins_continuation:score-=.4
    if method=='C' and len(dialogue)<2:score-=.55
    return {'episode':episode['episode'],'segments':[{'episode':episode['episode'],'start':round(start,2),'end':round(end,2),'start_stamp':stamp(start),'end_stamp':stamp(end)}],
        'duration':round(end-start,2),'method':method,'score':round(max(0,score),3),
        'ratings':{'hook':round(hook,2),'cliffhanger':round(cliff,2),'comprehension_proxy':round(comprehension,2),'tension':round(tension,2),'feasibility':feasibility},
        'hook':(_brief(h) if not hook_timing_uncertain else 'Potential hook in partially timed event; precise first-three-second content not established.'), 'hook_event_id':h['id'] if h else None,'cliffhanger':_brief(c), 'cliffhanger_event_id':c['id'] if c else None,
        'unanswered_viewer_question':ledger['final_cut']['viewer_question'], 'ledger':ledger, 'evidence_event_ids':list(dict.fromkeys([x for x in ([h['id']] if h else [])+([c['id']] if c else [])+ledger['comprehension']['conflict_evidence_ids']+ledger['comprehension']['stakes_evidence_ids']])),
        'warnings':warnings,'stats':{'dialogue_events':len(dialogue),'speakers':len(speakers)},'scoring_provenance':'untrained deterministic editorial heuristic; not an LLM or a performance predictor'}


def interesting_events(episode,limit=10):
    ranked=sorted(episode['events'], key=lambda e:(-event_signal(e)[0],e['start'],e['id']))
    chosen=[]
    for e in ranked:
        if event_signal(e)[0] < 2.2:break
        if any(abs(e['start']-x['start'])<2.5 for x in chosen):continue
        chosen.append(e)
        if len(chosen)>=limit:break
    return chosen


def anchors_for_episode(episode):
    """Factual scene/dialogue/action boundary proposals near impactful events."""
    events=episode['events']
    peaks=interesting_events(episode)
    starts=set()
    for p in peaks:
        near=[e for e in events if e['kind'] in ('dialogue','action') and p['start']-8<=e['start']<=p['start']+2]
        near=sorted(near,key=lambda e:(abs(e['start']-p['start']),e['kind']!='dialogue'))[:2]
        starts.update(round(e['start'],2) for e in near)
        starts.add(round(p['start'],2))
    if not starts: starts={round(e['start'],2) for e in events if e['kind']=='dialogue'}
    all_ends=sorted(set(round(e['end'],2) for e in events if e['kind'] in ('dialogue','action') and e['end']>e['start']))
    return sorted(starts),all_ends


def generate_candidates(episode,cap=250):
    starts,ends=anchors_for_episode(episode)
    result={}
    end_map={}
    for ev in episode['events']:
        if ev['kind'] in ('dialogue','action'):
            key=round(ev['end'],2)
            end_map[key]=max(end_map.get(key,0.),end_value(ev))
    for start in starts:
        if start+20>episode['duration']+.01:continue
        possible=[end for end in ends if start+20-.001<=end<=min(start+60,episode['duration'])+.001]
        if not possible:continue
        # Cheap ranking of end anchors before the full context-blind evaluation.
        scored=[]
        for end in possible:
            pos=end_map.get(end,0.)
            scored.append((pos,end))
        best=sorted(scored,key=lambda x:(-x[0],abs((x[1]-start)-35),x[1]))[:3]
        # Include a reasonable context-rich default without overfitting to the end signal.
        center=min(possible,key=lambda t:abs(t-(start+40)))
        for _,end in best+[(0.,center)]:
            key=(start,end)
            if key in result:continue
            ev=evaluate_clip(episode,start,end,'C')
            if ev:result[key]=ev
    sorted_candidates=sorted(result.values(),key=lambda c:(-c['score'],c['episode'],c['segments'][0]['start'],c['segments'][0]['end']))
    return sorted_candidates[:cap]


def baseline_for_episode(ep):
    peaks=interesting_events(ep)
    if not peaks:return []
    # Conventional: most dramatic point, 40-sec rigid selection from its nearest dialogue opening.
    selected=[]
    for peak in peaks[:8]:
        starts=sorted({e['start'] for e in ep['events'] if e['kind']=='dialogue' and peak['start']-5<=e['start']<=peak['start']+2},key=lambda v:abs(v-peak['start']))
        if not starts:continue
        s=starts[0]
        ends=[e['end'] for e in ep['events'] if e['kind'] in ('dialogue','action') and s+20<=e['end']<=s+60]
        if not ends:continue
        en=min(ends,key=lambda x:abs(x-(s+40)))
        c=evaluate_clip(ep,s,en,'A')
        if c:selected.append(c)
    return sorted(selected,key=lambda c:-c['score'])[:2]


def overlap_ratio(a,b):
    A=a['segments'][0];B=b['segments'][0]
    if A['episode']!=B['episode']:return 0.
    intersection=max(0,min(A['end'],B['end'])-max(A['start'],B['start']))
    union=max(A['end'],B['end'])-min(A['start'],B['start'])
    return intersection/union if union else 0


def _dedup(candidates,max_total=12,max_per_episode=1,threshold=.66):
    result=[];epcount=Counter()
    # Small cut-selection tie-break favors an actual stronger end beat when scores are near equal.
    # Applies to all episodes rather than hard-coding a favorite scene.
    def editorial_priority(c):
        return c['score'] + .10 * (c['ratings']['cliffhanger']/10.0)
    for c in sorted(candidates,key=lambda c:(-editorial_priority(c),c['episode'],c['segments'][0]['start'])):
        if epcount[c['episode']]>=max_per_episode:continue
        if any(overlap_ratio(c,x)>=threshold for x in result):continue
        result.append(c);epcount[c['episode']]+=1
        if len(result)>=max_total:break
    return result


def _enrich(ranked,candidates,episodes,method):
    by_episode={e['episode']:e for e in episodes}
    output=[]
    for rank,item in enumerate(ranked,1):
        c=dict(item); c['rank']=rank;c['promo_id']=f'CG-{method}-{rank:02d}'
        c['main_emotional_conflict'] = _brief(next((e for e in by_episode[c['episode']]['events'] if e['id'] in c['ledger']['comprehension']['conflict_evidence_ids']),None))
        c['why_it_works']=('Potential opening tension (' if c['ledger']['opening_first_3_seconds']['hook_timing_uncertain'] else 'Timed opening evidence (')+_brief(next((e for e in by_episode[c['episode']]['events'] if e['id']==c['hook_event_id']),None),65)+'); end assessment: '+c['unanswered_viewer_question'][:105]
        c['rank_reason']='Ranked by an uncalibrated editorial score with a small cliffhanger tie-break; not validated against audience behavior.'
        rivals=[a for a in candidates if a['episode']==c['episode'] and (a['segments']!=c['segments']) and overlap_ratio(a,c)>.18]
        materially_distinct=[a for a in rivals if abs(a['segments'][0]['start']-c['segments'][0]['start'])>=3 or abs(a['segments'][0]['end']-c['segments'][0]['end'])>=3 or a['hook_event_id']!=c['hook_event_id'] or a['cliffhanger_event_id']!=c['cliffhanger_event_id']]
        if materially_distinct:rivals=materially_distinct
        rivals.sort(key=lambda x:(-x['score'],x['segments'][0]['start']))
        if rivals:
            other=rivals[0]
            c['cut_comparison']={'chosen':{'segments':c['segments'],'score':c['score'],'opening':c['hook'],'ending':c['cliffhanger'],'question':c['unanswered_viewer_question']},
              'best_rejected':{'segments':other['segments'],'score':other['score'],'opening':other['hook'],'ending':other['cliffhanger'],'question':other['unanswered_viewer_question']},
              'comprehension_proxy_tradeoff':{'chosen':c['ratings']['comprehension_proxy'],'rejected':other['ratings']['comprehension_proxy']},
              'relative_duration_seconds':round(c['duration']-other['duration'],2),
              'opening_difference':('Different opening evidence or timing' if c['hook_event_id']!=other['hook_event_id'] or c['ledger']['opening_first_3_seconds']['hook_timing_uncertain']!=other['ledger']['opening_first_3_seconds']['hook_timing_uncertain'] else 'Same leading opening evidence'),
              'ending_difference':('Different last-event evidence / unresolved claim' if c['cliffhanger_event_id']!=other['cliffhanger_event_id'] or c['ledger']['final_cut']['question_type']!=other['ledger']['final_cut']['question_type'] else 'Same end evidence; duration or context differs'),
              'why_selected':(('Chosen ends on ['+_brief(next((e for e in by_episode[c['episode']]['events'] if e['id']==c['cliffhanger_event_id']),None),65)+'], while the rejected cut ends on ['+_brief(next((e for e in by_episode[c['episode']]['events'] if e['id']==other['cliffhanger_event_id']),None),65)+']. ') if c['cliffhanger_event_id']!=other['cliffhanger_event_id'] else ('Same closing beat, different opening context: chosen ['+c['hook'][:55]+'], alternative ['+other['hook'][:55]+']. '))+'Preference is heuristic; an editor must check footage.',
              'uncertainty':'Only screenplay text available; footage and true audience performance unmeasured.'}
        else:c['cut_comparison']=None
        output.append(c)
    return output


def run(pack, final_count=12, minimum_score=5.3):
    episodes=pack['episodes']
    candidates=[]; baseline=[]; ep_stats=[]
    for e in episodes:
        ranked=generate_candidates(e)
        candidates.extend(ranked)
        one_baseline=baseline_for_episode(e)
        baseline.extend(one_baseline)
        ep_stats.append({'episode':e['episode'],'scenes':len(e['scenes']),'events':len(e['events']),'duration_seconds':e['duration'],'candidates':len(ranked),'baseline_candidates':len(one_baseline), 'warnings':e['warnings']})
    cands_c=sorted(candidates,key=lambda x:-x['score'])
    # Comparison methods use exactly the same candidate set, with B removing the context-blind criterion.
    b_cands=[]
    ep_by_number={e['episode']:e for e in episodes}
    for c in cands_c:
        s=c['segments'][0];b=evaluate_clip(ep_by_number[c['episode']],s['start'],s['end'],'B')
        if b:b_cands.append(b)
    final_c=_dedup([c for c in cands_c if c['score']>=max(minimum_score,5.65) and c['ratings']['hook']>=4.0 and c['ratings']['cliffhanger']>=4.25 and c['ledger']['final_cut']['question_type'] in ('explicit_question','inferred_consequence') and not c['ledger']['comprehension']['major_context_switch_possible'] and not any('Opening dialogue begins as a continuation' in w for w in c['warnings']) and not c['ledger']['editorial_risks']['retrospective_opening_possible'] and not c['ledger']['editorial_risks']['opening_question_answered_soon']],final_count)
    final_b=_dedup(b_cands,final_count)
    final_a=_dedup(baseline,final_count)
    outputs={m:_enrich(v,(cands_c if m=='C' else b_cands if m=='B' else baseline),episodes,m) for m,v in [('A',final_a),('B',final_b),('C',final_c)]}
    warnings_count=sum(len(e['warnings']) for e in episodes)
    return {'summary':{'source_files_found':pack['files_found'],'episodes_processed':len(episodes),'episode_numbers':[e['episode'] for e in episodes],'scenes_parsed':sum(len(e['scenes']) for e in episodes),'events_parsed':sum(len(e['events']) for e in episodes),'parse_errors':len(pack['errors']),'parse_warnings':warnings_count,'candidate_windows_generated_and_evaluated':len(candidates),'baseline_candidates':len(baseline),'final_C':len(outputs['C']),'final_B':len(outputs['B']),'final_A':len(outputs['A']),'model_calls':0,'mode':'offline heuristic baseline with context-isolated evidence; NOT a run of an LLM','minimum_C_score':minimum_score,'scoring_warning':'Numerical scores are uncalibrated heuristics, not audience quality or validation metrics.'},
     'per_episode':ep_stats,'candidates_C':cands_c,'candidates_B':b_cands,'candidates_A':baseline,'outputs':outputs,'errors':pack['errors']}


def validate_output(pack,result):
    eps={e['episode']:e for e in pack['episodes']}
    violations=[];warnings=[]
    for method,items in result['outputs'].items():
        for item in items:
            episode=eps.get(item['episode']);name=item.get('promo_id','unknown')
            if not episode:violations.append(name+': episode unknown');continue
            last_end=-1
            for s in item['segments']:
                if s['episode']!=item['episode']:violations.append(name+': episode mismatch')
                if not (0<=s['start']<s['end']<=episode['duration']+.01):violations.append(name+': timeline out of range')
                if s['start']<last_end:violations.append(name+': segments out of order')
                last_end=s['end']
            if not 20<=item['duration']<=60: violations.append(name+': clip duration out of bounds')
            known={e['id'] for e in episode['events']}
            ids=item['evidence_event_ids']+item['ledger']['opening_first_3_seconds']['evidence_ids']+item['ledger']['final_cut']['evidence_ids']
            for id_ in ids:
                if id_ not in known:violations.append(name+': nonexistent event '+id_)
            lo=item['segments'][0]['start'];hi=item['segments'][-1]['end']
            emap={e['id']:e for e in episode['events']}
            for id_ in ids:
                if id_ in emap and not _overlap(emap[id_],lo,hi):violations.append(name+': evidence outside clip '+id_)
            hook_id=item['hook_event_id']
            if hook_id in emap and not _overlap(emap[hook_id],lo,min(hi,lo+3)):
                violations.append(name+': hook outside first 3 seconds')
            if item['ledger']['opening_first_3_seconds']['hook_timing_uncertain'] and item['ratings']['hook']>=4:violations.append(name+': strong hook on partial event without proof')
            if item['cliffhanger_event_id']!=item['ledger']['final_cut']['lead_event_id']:
                violations.append(name+': cliffhanger citation differs from ledger ending evidence')
            if item['ledger']['editorial_risks'].get('retrospective_opening_possible') and item['ratings']['hook']>=4:
                violations.append(name+': high-confidence hook claimed for retrospective opener')
            if item['ledger']['editorial_risks'].get('opening_question_answered_soon') and item['ratings']['hook']>=4:
                violations.append(name+': high-confidence hook claimed for immediately answered question')
            if item['warnings']:warnings.append(name+': '+'; '.join(item['warnings']))
    return {'passed':not violations,'violations':violations,'editorial_warnings':warnings,'validated_recommendations':sum(len(items) for items in result['outputs'].values()),'validity_scope':'mechanical timestamp/provenance checks only, not true viewer performance'}


def metrics(pack,result):
    """Observed structural proxy measures, not real retention/conversion."""
    out={}
    for method,items in result['outputs'].items():
        def rate(pred):return round(sum(bool(pred(p)) for p in items)/len(items),3) if items else None
        out[method]={'n':len(items),'avg_heuristic_hook':round(sum(c['ratings']['hook'] for c in items)/len(items),2) if items else None,'avg_comprehension_proxy':round(sum(c['ratings']['comprehension_proxy'] for c in items)/len(items),2) if items else None,'hook_ge_4_rate':rate(lambda p:p['ratings']['hook']>=4),'question_evidence_rate':rate(lambda p:p['ledger']['final_cut']['question_type'] in ('explicit_question','inferred_consequence')),'weak_context_warning_rate':rate(lambda p:any('comprehension' in w.lower() for w in p['warnings'])),'total_distinct_episodes':len(set(c['episode'] for c in items))}
    return {'method_metrics':out,'caveat':'All reported rates are mechanical/heuristic proxy measurements on selections. Not blind human or audience measurements; methods have different score functions. No causal superiority claim.'}
