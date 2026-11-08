"""Loss-aware parser of timestamped Kuku-style screenplay TXT files inside ZIPs."""
from __future__ import annotations
import io, json, re, zipfile
from pathlib import Path

TIME = r"\d{1,3}:\d{2}(?:\.\d{1,3})?"
EVENT = re.compile(rf"(?m)^\*\*(?P<tag>[^\r\n]+?)\*\*\s*\r?\nStart:\s*\(?(?P<start>{TIME})\)?\s*\|\s*End:\s*\(?(?P<end>{TIME})\)?\s*\r?\n")
SCENE = re.compile(r"(?m)^SCENE\s+(\d+)\s*$")
SCENE_START = re.compile(rf"(?mi)^Scene start:\s*({TIME})\s*$")
SCENE_END = re.compile(rf"(?mi)^Scene end:\s*({TIME})\s*$")
HEADING = re.compile(r"(?mi)^Scene heading:\s*(.*?)\s*$")
EPISODE = re.compile(r"(?m)^EPISODE NUMBER:\s*Episode\s+(\d+)\s*$", re.I)


def to_seconds(value: str) -> float:
    if not re.fullmatch(TIME, value.strip()):
        raise ValueError(f"Invalid timestamp: {value!r}")
    mm, ss = value.split(':')
    if float(ss) >= 60: raise ValueError(f"Invalid seconds in {value!r}")
    return round(60 * int(mm) + float(ss), 3)


def stamp(seconds: float) -> str:
    mm, seconds = divmod(round(seconds, 2), 60)
    return f"{int(mm):02d}:{seconds:05.2f}"


def _after(text: str, prefix: str) -> str:
    m = re.search(rf"(?m)^{re.escape(prefix)}\s*(.*)$", text)
    return m.group(1).strip() if m else ''


def parse_episode(content: str, filename: str, fallback_number: int | None = None) -> dict:
    txt = content.lstrip('\ufeff').replace('\r\n','\n')
    m = EPISODE.search(txt)
    number = int(m.group(1)) if m else fallback_number
    if number is None: raise ValueError('Missing episode number in source and filename')
    warnings = []
    if not m: warnings.append('Missing episode metadata; episode inferred from filename')
    scene_hits = list(SCENE.finditer(txt))
    scenes=[]
    for j, match in enumerate(scene_hits):
        body_end = scene_hits[j + 1].start() if j + 1 < len(scene_hits) else len(txt)
        body = txt[match.end():body_end]
        heading = HEADING.search(body); start = SCENE_START.search(body); end = SCENE_END.search(body)
        s_start = to_seconds(start.group(1)) if start else None
        s_end = to_seconds(end.group(1)) if end else None
        scene_id=f"E{number:03d}-S{int(match.group(1)):02d}"
        if s_start is None or s_end is None: warnings.append(f'{scene_id}: missing start/end time')
        if s_start is not None and s_end is not None and s_end < s_start: warnings.append(f'{scene_id}: end before start')
        scenes.append({'id':scene_id,'number':int(match.group(1)),'heading':heading.group(1).strip() if heading else '', 'start':s_start,'end':s_end,'source_line':txt.count('\n',0,match.start())+1,'_pos':match.start()})
    events=[]; matches=list(EVENT.finditer(txt))
    for i, match in enumerate(matches):
        start, end = to_seconds(match.group('start')), to_seconds(match.group('end'))
        tag=match.group('tag').strip().rstrip(':')
        following = matches[i+1].start() if i+1<len(matches) else len(txt)
        part=txt[match.end():following]
        part = re.split(r'(?m)^SCENE\s+\d+\s*$|^--- SCRIPT END ---\s*$',part,maxsplit=1)[0]
        body=part.strip()
        applicable = next((s for s in reversed(scenes) if s['_pos']<=match.start()),None)
        scene_id=applicable['id'] if applicable else None
        if scene_id is None: warnings.append(f'Unassigned event at line {txt.count(chr(10),0,match.start())+1}')
        if end <= start:
            warnings.append(f'E{number:03d} event {i+1}: invalid boundaries {start}-{end}')
        if applicable and applicable['start'] is not None and applicable['end'] is not None:
            if start < applicable['start'] - .1 or end > applicable['end'] + .1:
                warnings.append(f'E{number:03d} event {i+1}: outside scene span')
        kind='camera' if tag.upper() == 'CAMERA' else 'action' if tag.upper() == 'ACTION' else 'sound' if tag.upper() in ('SOUND FX','SFX','MUSIC') else 'dialogue'
        speaker = re.split(r'\s*\(',tag,maxsplit=1)[0].strip() if kind=='dialogue' else ''
        line = txt.count('\n',0,match.start())+1
        events.append({'id':f'E{number:03d}-V{i+1:04d}', 'episode':number,'scene_id':scene_id,'kind':kind,'speaker':speaker,'tag':tag,'start':start,'end':end,'start_stamp':match.group('start'),'end_stamp':match.group('end'),'text':body,'source':{'filename':filename,'line':line}})
    unmatched_start=len(re.findall(r'(?m)^Start:\s*',txt))-len(matches)
    if unmatched_start: warnings.append(f'{unmatched_start} unrecognized timed blocks')
    if not scenes: warnings.append('No scenes parsed')
    if not events: warnings.append('No events parsed')
    for s in scenes: s.pop('_pos',None)
    duration=max([e['end'] for e in events]+[s['end'] for s in scenes if s['end'] is not None]+[0.])
    return {'episode':number, 'filename':filename,'logline':_after(txt,'EPISODE LOGLINE:'),'continuity':_after(txt,'CONTINUITY NOTES:'),'scenes':scenes,'events':events,'duration':duration,'warnings':warnings}


def parse_zip(path_or_buffer) -> dict:
    if hasattr(path_or_buffer,'read'):
        blob=path_or_buffer.read(); z=zipfile.ZipFile(io.BytesIO(blob))
    else: z=zipfile.ZipFile(str(path_or_buffer))
    episodes=[]; errors=[]
    with z:
        names=sorted(n for n in z.namelist() if n.lower().endswith('.txt') and not n.startswith('__MACOSX/') and not Path(n).name.startswith('.'))
        for filename in names:
            if '..' in Path(filename).parts: errors.append(f'Unsafe filename skipped: {filename}');continue
            episode_hint=re.search(r'episode[-_ ]?(\d+)',Path(filename).name,re.I)
            fallback=int(episode_hint.group(1)) if episode_hint else None
            try:
                content=z.read(filename).decode('utf-8-sig')
                episode=parse_episode(content,filename,fallback)
                if episode_hint and episode['episode']!=fallback: episode['warnings'].append('Filename episode number differs from metadata')
                episodes.append(episode)
            except (ValueError,UnicodeError,RuntimeError) as e: errors.append(f'{filename}: {type(e).__name__}: {e}')
    seen=set()
    for e in episodes:
        if e['episode'] in seen: errors.append(f"Duplicate episode {e['episode']}")
        seen.add(e['episode'])
    return {'episodes':sorted(episodes,key=lambda x:x['episode']),'errors':errors, 'files_found':len(names)}
