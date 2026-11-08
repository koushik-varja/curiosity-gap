"""Optional replaceable OpenAI-compatible JSON critic. Requires explicit API credentials.
No network connection or AI service is necessary for the default offline pipeline.
"""
from __future__ import annotations
import hashlib, json, os, re, time, urllib.error, urllib.request
from .engine import _overlap

class ModelError(Exception):pass

class OpenAICompatibleAdapter:
    def __init__(self,base_url=None,model=None,key=None,timeout=35,retries=2,temperature=0.0):
        self.base_url=(base_url or os.environ.get('CG_API_BASE','https://api.openai.com/v1')).rstrip('/')
        self.model=model or os.environ.get('CG_MODEL','')
        self.key=key or os.environ.get('CG_API_KEY','')
        self.timeout=timeout;self.retries=retries;self.temperature=temperature
        if not self.model or not self.key:raise ModelError('CG_MODEL and CG_API_KEY are required when mode=api')

    def complete(self, system, payload):
        request_body={'model':self.model,'temperature':self.temperature,'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]}
        request=urllib.request.Request(self.base_url+'/chat/completions',data=json.dumps(request_body).encode(),headers={'Authorization':f'Bearer {self.key}','Content-Type':'application/json'},method='POST')
        last=None
        for attempt in range(self.retries+1):
            try:
                with urllib.request.urlopen(request,timeout=self.timeout) as response:
                    raw=response.read().decode('utf8')
                obj=json.loads(raw)
                message=obj['choices'][0]['message']['content']
                # some providers return structured content arrays
                if isinstance(message,list):message=''.join(x.get('text','') for x in message if isinstance(x,dict))
                clean=re.sub(r'^```(?:json)?\s*|\s*```$','',message.strip(),flags=re.I)
                try:assessment=json.loads(clean)
                except (ValueError,TypeError):assessment=None
                return {'raw_response':raw,'raw_model_content':message,'assessment':assessment,'usage':obj.get('usage',{})}
            except (urllib.error.URLError,TimeoutError,ValueError,KeyError,IndexError,TypeError) as exc:
                last=exc
                if attempt<self.retries:time.sleep(.4*(attempt+1))
        raise ModelError(f'Provider response failed after retries: {type(last).__name__}: {last}')

SYSTEM="""You are a skeptical first-time viewer. Only clip-contained timed evidence is supplied. No summaries, previous scenes, future scenes, inferred spoken word timing, or invented footage. A partial event's text is unavailable on purpose. Return a single JSON object with EXACT fields: hook_strength, standalone_comprehension, unresolved_curiosity (numbers 0-10), reason (specific), hook_evidence_id (string or null), cliff_evidence_id (string or null), unanswered_question (string; or 'unknown'), quality_warnings (array of strings). Strong hook >=7 requires a fully contained evidence event within the first three seconds. Strong unresolved curiosity >=7 requires cited end-event evidence in the last five seconds and a concrete open question. If either is unverified, score conservatively and describe uncertainty in warnings. Do not invent facts or claim measured audience behavior."""


def isolated_payload(episode, candidate):
    """Security boundary: do not expose words from events that extend outside the cut."""
    s=candidate['segments'][0];start=s['start'];end=s['end']
    events=[]
    for e in episode['events']:
        if not _overlap(e,start,end):continue
        partial=e['start']<start-.001 or e['end']>end+.001
        events.append({'id':e['id'],'kind':e['kind'],'speaker':e['speaker'],
            'start':max(start,e['start']),'end':min(end,e['end']),
            'partial_event':partial,'text':('[PARTIAL EVENT — content unavailable because timing crosses clip boundary]' if partial else e['text'])})
    return {'clip_start':start,'clip_end':end,'duration':candidate['duration'],'events':events,
            'time_precision_note':'Event-level only; exact word/shot timing is not provided.'}


def validate_assessment(assessment,payload):
    if not isinstance(assessment,dict):raise ModelError('Assessment is not a JSON object')
    fields={'hook_strength','standalone_comprehension','unresolved_curiosity','reason','hook_evidence_id','cliff_evidence_id','unanswered_question','quality_warnings'}
    if not fields.issubset(assessment):raise ModelError('Missing required assessment fields: '+str(sorted(fields-set(assessment))))
    ev={e['id']:e for e in payload['events']}
    for key in ['hook_strength','standalone_comprehension','unresolved_curiosity']:
        val=assessment[key]
        if type(val) not in (int,float) or not 0<=val<=10:raise ModelError(f'Invalid 0-10 {key}')
    for field in ['reason','unanswered_question']:
        if not isinstance(assessment[field],str) or len(assessment[field].strip())<8:raise ModelError('Missing substantive '+field)
    warnings=assessment['quality_warnings']
    if not isinstance(warnings,list) or any(not isinstance(w,str) or not w.strip() for w in warnings):raise ModelError('Malformed quality_warnings')
    hook=assessment['hook_evidence_id'];cliff=assessment['cliff_evidence_id']
    for field,id_,lo,hi in [('hook_evidence_id',hook,payload['clip_start'],payload['clip_start']+3),
                            ('cliff_evidence_id',cliff,payload['clip_end']-5,payload['clip_end'])]:
        if id_ is None:continue
        if id_ not in ev:raise ModelError(f'Unseen evidence event: {id_}')
        e=ev[id_]
        if not (e['start']<hi-.0001 and e['end']>lo+.0001):raise ModelError(f'{field} outside allowed time range')
    if assessment['hook_strength']>=5 and hook is None:raise ModelError('Unsupported high hook score: no evidence ID')
    if hook and assessment['hook_strength']>=7:
        e=ev[hook]
        if e['partial_event'] or e['start']<payload['clip_start']-.01 or e['end']>payload['clip_start']+3+.01:
            raise ModelError('Strong hook incorrectly attributes full textual content to partial first-three-second event')
    if assessment['unresolved_curiosity']>=5 and cliff is None:raise ModelError('Unsupported high cliff score: no evidence ID')
    if assessment['unresolved_curiosity']>=7 and assessment['unanswered_question'].lower().strip() in ('unknown','none','no clear unanswered question','not sure'):
        raise ModelError('Unsupported high cliff score without concrete unanswered question')
    if cliff and assessment['unresolved_curiosity']>=7 and ev[cliff]['partial_event']:
        raise ModelError('Strong cliff unsupported by incomplete source event')
    return True


def run_optional_model(pack,baseline_results,limit=20,adapter=None,final_count=12):
    """Real inference selects a separate M shortlist. No inference -> offline C unchanged."""
    from .engine import _dedup, _enrich
    adapter=adapter or OpenAICompatibleAdapter()
    episodes={e['episode']:e for e in pack['episodes']}
    # Favor candidates already structurally eligible; include a genuine alternative to each
    # interesting moment rather than wasting calls on unrelated single finalists.
    pool=[c for c in baseline_results['candidates_C'] if c['ratings']['hook']>=4 and c['ratings']['cliffhanger']>=4
          and c['ledger']['final_cut']['question_type'] in ('explicit_question','inferred_consequence')]
    selected=[]; explored=set()
    for c in pool:
        ep=c['episode']
        if ep in explored:continue
        explored.add(ep);selected.append(c)
        if len(selected)>=max(1,limit//2):break
    for c in list(selected):
        if len(selected)>=limit:break
        alts=[a for a in pool if a['episode']==c['episode'] and a['segments']!=c['segments']
              and abs(a['segments'][0]['end']-c['segments'][0]['end'])>=2]
        if alts:selected.append(alts[0])
    attempts=[];accepted=[]
    for c in selected[:limit]:
        payload=isolated_payload(episodes[c['episode']],c)
        item={'episode':c['episode'],'segments':c['segments'],
              'payload_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),
              'provider_model':getattr(adapter,'model','test-provider'), 'attempted_at_unix':time.time()}
        start=time.perf_counter()
        try:
            reply=adapter.complete(SYSTEM,payload)
            item.update({'raw_provider_response':reply.get('raw_response'),'raw_model_content':reply.get('raw_model_content'),
                         'usage':reply.get('usage',{})})
            validate_assessment(reply.get('assessment'),payload)
            a=reply['assessment']
            score=round(.32*a['hook_strength']+.28*a['standalone_comprehension']+.33*a['unresolved_curiosity']+.07*c['ratings']['feasibility']-min(.6,len(a['quality_warnings'])*.12),3)
            modified=dict(c);modified['score']=score;modified['method']='M';modified['semantic_evaluation']=a
            modified['rank_reason']='Model-assisted weighted assessment, independently validated. Not measured viewer performance.'
            if a['hook_strength']>=5 and a['unresolved_curiosity']>=5 and score>=5.3:
                accepted.append(modified)
                item['eligible_for_model_ranking']=True
            else:item['eligible_for_model_ranking']=False
            item.update({'assessment':a,'status':'accepted'})
        except (ModelError,ValueError,TypeError) as e:
            item.update({'status':'failed','error':str(e)})
        item['latency_seconds']=round(time.perf_counter()-start,3)
        attempts.append(item)
    chosen=_dedup(accepted,max_total=final_count,max_per_episode=1)
    ranked=_enrich(chosen,accepted,list(episodes.values()),'M')
    for c in ranked:
        c['rank_reason']='Validated real model-assisted ranking; score is an editorial estimate, not audience performance.'
    return {'provider':getattr(adapter,'base_url','mock provider'),'model':getattr(adapter,'model','mock model'),
            'attempted':len(attempts),'accepted':sum(i['status']=='accepted' for i in attempts),
            'ranked_model_promos':ranked,'shortlist_size':len(ranked),'attempts':attempts,
            'note':'Separate model-assisted ranking, no offline overwrite; real scores need actual provider calls, human footage check still required.'}
