"""Offline, dependency-free private reviewer. Generated HTML never makes network requests."""
from __future__ import annotations
import json
from pathlib import Path

HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'none'; connect-src 'none'">
<title>CURIOSITY GAP — local editorial review</title>
<style>
:root{color-scheme:light;font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;color:#15263e;background:#f5f8fb}body{margin:0}header{background:#13253e;color:white;padding:30px max(22px,calc((100% - 1140px)/2));box-shadow:0 3px 18px #101e3114}header .tiny{font-size:12px;letter-spacing:.12em;color:#8fdbd1;font-weight:800}h1{font-size:34px;letter-spacing:-.035em;margin:7px 0 2px}header p{margin:5px 0;color:#d1dde7;font-size:13px}.wrap{max-width:1140px;margin:24px auto;padding:0 22px}.notice{border-left:4px solid #c77d2a;background:#fff6e5;padding:12px 15px;border-radius:7px;color:#675022;font-size:13px}.tools{display:flex;gap:15px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:22px 0}.control{display:flex;align-items:center;gap:9px;font-size:13px}.control select{border:1px solid #d0dce6;border-radius:9px;padding:9px 12px;background:white;font:inherit;min-width:160px}.tool-link{font-size:12px;color:#076b75}.stats{display:flex;gap:9px;flex-wrap:wrap}.stat{background:#e6f2f1;border-radius:7px;padding:8px 13px;font-size:12px;font-weight:700;color:#176b69}#cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(305px,1fr));gap:15px}.card{border:1px solid #e1e9f0;background:white;border-radius:15px;box-shadow:0 6px 18px #21365309;padding:19px}.top{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:11px}.rank{font-weight:800;font-size:14px}.time{font-size:12px;color:#315b69;font-variant-numeric:tabular-nums;background:#eaf4f4;border-radius:6px;padding:4px 7px}.field{margin:14px 0}.label{font-size:10px;font-weight:800;letter-spacing:.10em;color:#688192;text-transform:uppercase;margin-bottom:5px}.value{font-size:13px;line-height:1.55;overflow-wrap:anywhere}.warn{background:#fff5eb;border-radius:7px;padding:8px;color:#80542a;font-size:12px;margin:4px 0}details{border-top:1px solid #e5edf2;padding-top:10px;margin-top:10px}summary{cursor:pointer;color:#087980;font-weight:750;font-size:12px}pre{max-height:250px;overflow:auto;white-space:pre-wrap;font-size:11px;background:#eef4f7;padding:10px;border-radius:8px}.none{margin:40px 0;color:#667}
</style></head><body>
<header><div class="tiny">KUKU AI GENERALIST · OFFLINE EDITOR DESK</div><h1>CURIOSITY GAP</h1><p>Review exact source boundaries, unresolved questions and rejected alternatives.</p></header>
<div class="wrap"><div class="notice"><strong>Private material.</strong> This self-contained file contains screenplay-derived excerpts. Keep it off public repositories and hosted services. Heuristic rankings require editor and footage review; no real LLM calls or audience studies are implied.</div>
<div class="tools"><div class="control"><label for="episode-filter">Episode</label><select id="episode-filter"><option value="all">All shortlisted episodes</option></select></div><div class="stats"><span class="stat" id="count"></span><span class="stat">Local · no external requests</span></div><div><a class="tool-link" href="07_ranked_promos_PRIVATE.json" download>Download full JSON</a> &nbsp; <a class="tool-link" href="ranked_editorial_cards_PRIVATE.csv" download>Download CSV</a></div></div>
<div id="cards"></div></div>
<script id="data" type="application/json">__DATA_JSON__</script>
<script>
'use strict';
const data=JSON.parse(document.querySelector('#data').textContent);
const records=data.records,filter=document.querySelector('#episode-filter'),cards=document.querySelector('#cards');
function node(type,klass,text){const e=document.createElement(type);if(klass)e.className=klass;if(text!==undefined)e.textContent=String(text);return e;}
const episodes=[...new Set(records.map(r=>r.episode))].sort((a,b)=>a-b);
episodes.forEach(e=>{const option=node('option','',`Episode ${String(e).padStart(2,'0')}`);option.value=e;filter.appendChild(option);});
function detail(target,title,contents){const d=node('details'),s=node('summary','',title),p=node('pre','',typeof contents==='string'?contents:JSON.stringify(contents,null,2));d.append(s,p);target.appendChild(d);}
function field(target,name,value){const wrapper=node('div','field');wrapper.append(node('div','label',name),node('div','value',value||'Uncertain — needs editor review'));target.appendChild(wrapper);}
function render(){cards.replaceChildren();const filtered=records.filter(r=>filter.value==='all'||String(r.episode)===filter.value);document.querySelector('#count').textContent=`${filtered.length} review cards`;
 if(!filtered.length){cards.appendChild(node('p','none','No matching results'));return;}
 filtered.forEach(r=>{const c=node('article','card'),top=node('div','top'),seg=r.segments[0];top.append(node('div','rank',`#${r.rank} · Episode ${String(r.episode).padStart(2,'0')}`),node('div','time',`${seg.start_stamp} — ${seg.end_stamp}`));c.appendChild(top);
 field(c,'Opening evidence',r.hook);field(c,'Final beat',r.cliffhanger);field(c,'Unanswered / uncertain',r.unanswered_viewer_question);
 field(c,'Why ranked',r.rank_reason);
 for(const warning of r.warnings||[])c.appendChild(node('p','warn',`Review: ${warning}`));
 detail(c,'Viewer-knowledge evidence',r.ledger);
 if(r.cut_comparison)detail(c,'Chosen cut vs rejected alternative',r.cut_comparison);
 field(c,'Verification','Validate actual footage, visible first 3 seconds, continuous narrative, and final cut before posting.');
 cards.appendChild(c);});}
filter.addEventListener('change',render);render();
</script></body></html>'''


def render_review(result, output_path):
    """Generate a *private* single-file viewer for the actual evaluated shortlist."""
    rows=result['outputs']['C']
    payload=json.dumps({'records':rows},ensure_ascii=False,allow_nan=False).replace('</','<\\/').replace('\u2028','\\u2028')
    data=HTML.replace('__DATA_JSON__',payload)
    Path(output_path).write_text(data,encoding='utf-8')
