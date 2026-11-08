"""Optional lightweight web interface; import streamlit only for UI run."""
import io,json,csv
import streamlit as st
from curiosity_gap.parser import parse_zip
from curiosity_gap.engine import run,validate_output,metrics

st.set_page_config(page_title='CURIOSITY GAP | Editor desk',layout='wide',page_icon='🎬')
st.title('CURIOSITY GAP')
st.caption('Screenplay-grounded promo discovery · cut comparison · offline editor-assistance prototype')
st.warning('Screenplays and exported results may be confidential. Do not deploy with Kuku source data in a public repository.')
st.markdown('**Creative ratings are untrained deterministic proxies, not audience or LLM scores.** An editor must approve all final cuts.')
file=st.file_uploader('Upload a ZIP of timestamped episode TXT files',type=['zip'])
n=st.slider('Max ranked promos',1,20,12)
threshold=st.slider('Minimum heuristic score',0.0,10.0,5.3,0.1)
if file and st.button('Find promo cuts',type='primary'):
    with st.spinner('Reading source events and testing candidate boundaries...'):
        try:
            pack=parse_zip(io.BytesIO(file.getvalue()))
            if not pack['episodes']:st.error('No screenplay episodes could be parsed.');st.stop()
            result=run(pack,n,threshold)
            report=validate_output(pack,result);comparison=metrics(pack,result)
            st.session_state['run']={'pack':pack,'result':result,'report':report,'comparison':comparison}
        except Exception as exc:st.error(f'Unable to process input: {exc}')
if 'run' in st.session_state:
    data=st.session_state['run'];r=data['result'];report=data['report']
    col1,col2,col3,col4=st.columns(4)
    for col,label,v in [(col1,'Episodes processed',r['summary']['episodes_processed']),(col2,'Timed events',r['summary']['events_parsed']),(col3,'Candidate cuts',r['summary']['candidate_windows_generated_and_evaluated']),(col4,'Validation violations',len(report['violations']))]: col.metric(label,v)
    st.subheader('Ranked editorial decisions')
    method=st.selectbox('Selection strategy',options=['C','B','A'],format_func=lambda k:{'C':'C · Curiosity Gap (offline)','B':'B · Cut optimization','A':'A · Fixed-window baseline'}[k])
    for c in r['outputs'][method]:
        seg=c['segments'][0]
        with st.expander(f"#{c['rank']}  ·  Episode {c['episode']:02d}  ·  {seg['start_stamp']} – {seg['end_stamp']}  ·  {c['score']:.2f} proxy",expanded=c['rank']==1):
            st.write('**Opening hook:**',c['hook']);st.write('**Final cut:**',c['cliffhanger']);st.write('**Unanswered question:**',c['unanswered_viewer_question']);st.write('**Why the tool chose it:**',c['rank_reason'])
            if c['warnings']:st.info('Review: '+'; '.join(c['warnings']))
            ledger=c['ledger']
            tab1,tab2=st.tabs(['What this viewer knows','Chosen cut vs alternative'])
            with tab1:st.json(ledger)
            with tab2:
                if c['cut_comparison']:st.json(c['cut_comparison'])
                else:st.caption('No eligible competing cut in evaluated candidates.')
    st.subheader('Download private derived outputs')
    st.download_button('Ranked promos (JSON)',json.dumps(r['outputs'],ensure_ascii=False,indent=2),'ranked_promos_PRIVATE.json','application/json')
    st.download_button('Validation report (JSON)',json.dumps(report,ensure_ascii=False,indent=2),'validation_report.json','application/json')
    st.download_button('Proxy comparison (JSON)',json.dumps(data['comparison'],ensure_ascii=False,indent=2),'comparison.json','application/json')
    st.caption('For full unedited candidate logs and CSV use the CLI; this interface only exports selected views.')
