# CURIOSITY GAP

**Script → candidate promo moments → cut-boundary alternatives → context-isolated viewer ledger → editorial shortlist.**

An original, reproducible Python prototype for **Kuku AI Generalist Assignment, Problem 1**. It deliberately separates executable, verifiable source timing from subjective editorial judgments. The default **offline mode works without an API key**; its editorial scores are **uncalibrated textual heuristics**, not real viewer feedback or actual LLM judgments.

## Quick start (Python 3.10+)

```bash
# Run this command from the repository directory. No pip install is needed for CLI.
python -m curiosity_gap.cli --input "/path/to/private_screenplay_pack.zip" --out private_outputs

# Optional graphical editor desktop
pip install -r requirements.txt
streamlit run streamlit_app.py

# Tests
python -m pytest -q

# Optional test on actual confidential pack
CG_PRIVATE_PACK="/path/to/private_screenplay_pack.zip" python -m pytest -q
```

Windows PowerShell: `$env:CG_PRIVATE_PACK="C:\\path\\scripts.zip"; python -m pytest -q`. Windows can run the CLI using `python -m curiosity_gap.cli --input "C:\\path\\scripts.zip" --out private_outputs`.

**Public synthetic demo:** `examples/synthetic_episode.txt` is wholly fictional. Create a ZIP from the `.txt`, then pass it through `--input`. In Python:

```python
from zipfile import ZipFile
with ZipFile('synthetic.zip', 'w') as z:
    z.write('examples/synthetic_episode.txt', arcname='episode-001.txt')
```

## Editorial methodology

- **Parser:** preserves source file, scene ID, event ID, original timestamp precision and all timed camera/dialogue/action/SFX evidence. Captures malformed-event and scene-boundary warnings instead of suppressing them. Overlapping action/camera/dialogue is legitimate.
- **Opportunity mining:** transparent source-text signals (conflict, reversal, threat, questions, etc.), not a claim of trained semantic understanding.
- **Cut optimizer:** proposes 20–60-second one-piece windows anchored on spoken/action boundaries. No interpolation of footage and no fabricated multi-episode stitching.
- **Viewer Knowledge Ledger:** only the events inside the proposed clip enter this evaluator. Opening (3 s), inferred context, conflict, last seconds and a specifically labeled open question are recorded with event IDs. The offline ledger is a mechanical *approximation*, not a genuine simulated human viewer.
- **Skeptical check:** flags hook claims whose source events are not wholly delivered within three seconds, weak/missing ending questions, generic one-word cliffhangers, retrospective exposition, speaker-context shifts, dialogue continuation and potentially interrupted actions. Some issues still require editor judgment.
- **Three methods:** A = rigid window after a promising moment; B = choose among tested cuts; C = conservative selection among those tested cuts with explicit hook/ending evidence gates and comprehension/ledger caution. Real model-assisted ranking, when used, is exported separately as M. The comparison is *proxy-only*, not independent audience/user research. Selection changes can improve one proxy while worsening another.
- **Decision cards:** each ranked promo contains start/end stamps, literal hook/cliff evidence, uncertainty, cut comparison, provenance and warnings.

## Run artifacts (private)

`private_outputs/` contains `01_run_summary.json`, `02_episode_coverage.json`, `03_normalized_episodes_PRIVATE.json`, complete `04...06` candidate logs, `07_ranked_promos_PRIVATE.json`, validation and metric reports, rejection register, manifest and CSV. Each file is generated directly by the executable. Avoid manually rewriting raw outputs. `--mode api` additionally writes raw provider attempts to `10_optional_model_raw_PRIVATE.json` and a genuinely model-reordered final portfolio to `12_model_assisted_ranked_PRIVATE.json` (only after actual validated inference). Offline C is never silently rewritten. The CLI also generates a private local `PRIVATE_editor_review.html`, plus `13_paired_cut_structural_review_PRIVATE.json`.

Raw files contain **proprietary screenplay text**. **Never push the input pack or private output folder to GitHub, upload them to a public hosted demo, or paste them into a public issue.** `.gitignore` is a secondary safeguard, not permission to share. Give Kuku reviewers any necessary full-pack outputs through separately controlled share links.

## Optional swappable AI component (not required for offline execution)

The `/chat/completions` adapter accepts common OpenAI-compatible backends. It sends **only event data inside each clip**, not episode synopsis, surrounding scripts or future narrative. Source IDs and first/last-second evidence references are validated before accepting a provider JSON response. Retried failures are retained in raw run logs. When configured and genuinely executed, accepted source-grounded model judgments change a **separate** M ranking and are logged with raw responses, latency and usage where available. Without credentials, zero real model calls are made; mock tests prove integration, not model performance.

```bash
export CG_API_KEY="your-private-api-key"
export CG_MODEL="a-valid-model-offered-by-your-provider"
export CG_API_BASE="https://your-provider.example/v1"
python -m curiosity_gap.cli --input scripts.zip --out private_model_run --mode api --max-model-evals 20
```

The optional model critic drives a **separate model-assisted ranking M** after structured evidence validation, never overwriting the reproducible offline A/B/C rankings. No proprietary data should be sent to any service without appropriate permission and security review. Costs depend on provider, model and requests, and have not been measured in this assignment.

## Honest boundaries

1. **No final footage:** we cannot measure visual hook quality, viewer retention, spoken timing accuracy or editing feasibility without video.
2. **Not trained:** text heuristics mistake dramatic terms for good standalone scenes, and sometimes treat a question as an unresolved cliffhanger when a viewer might not care.
3. **Unverified audience performance:** numerical scores are proxies only, and one clip may be objectively timestamp-valid yet creatively weak.
4. **Single-pass local checks:** while the model adapter is independently configurable and tested for missing credentials / validation, API mode needs real credentials and a separately measured run before making quality claims.
5. **Human final review:** Kuku editor watches the candidate footage and chooses what to publish. Key future metrics: editor approval, editor time saved, retention in first 3 seconds, show starts and eventual audience conversion.

## Cost and scale concept

Parsing/scoring are local and can process just new episodes. Cache parsed events and individual clip evaluations by content hash for reruns. Limit expensive optional semantic calls to shortlisted windows, isolate the model behind an interface, track output schema failures and total token usage. The pipeline remains run-ready for unseen scripts that follow the documented timed-event schema.

## Integrity / interview disclosure

Use of AI in construction: ChatGPT (GPT-6) assisted architecture, source parser, rules, docs and tests. An observable tool error during development was the initial parser's failure to accept uppercase `SCENE START/END` labels; this was corrected and regression-tested. A source event crossing its declared scene boundary remained flagged as a data-quality warning. A second genuine mistake was an overly permissive model validator that accepted unsupported high scores; high-scoring evidence now requires in-clip, timing-compatible citations. The third corrective run has 41 passing tests, six conservative offline finalists from 2,220 candidates, zero real API calls and no demonstrated audience lift. All quality findings must be explained as heuristic or manually checked, not as blind human experiments.

## V2 corrective audit and private offline reviewer

Version **0.3.0** preserves the original 50-episode input parsing but tightens the quality gate; a full rerun selected **six** offline C recommendations, not a forced 12. The original 12-recommendation evidence is retained unchanged in the *separate private baseline archive*, not published with this repository. Always keep raw Kuku-derived outputs private.

```bash
python -m curiosity_gap.cli --input examples/synthetic_demo.zip --out synthetic_local_review
# Open synthetic_local_review/PRIVATE_editor_review.html in a local browser
```

The generated single-file HTML review desk supports episode filtering, expanding evidence ledgers and chosen/rejected cut comparisons and downloading adjacent JSON/CSV. It is written to the **private output folder** and contains screenplay-derived content; do not publicly host a full-pack version. The synthetic reviewer (1 card, 2 expandable panels) and private V3 reviewer (6 cards, 12 panels) passed Chromium/Playwright DOM interaction checks using local page content: rendering, opening panels, episode filter/reset and presence of JSON/CSV links. The referenced export files exist; actual browser download clicks from file URLs were not verified. This does not validate video editing, uploaded media or deployment. The Streamlit interface remains optional and unverified: Streamlit is absent, and the available package source supplied no installable version. The verified primary runnable prototype is the Python CLI with synthetic and private ZIP inputs.

**Model safety:** isolated model payloads withhold the actual text of timed events crossing clip boundaries, so the model cannot quote dialogue from outside the selected clip. Responses with absent reasons, unsupported high scores, ungrounded IDs, malformed fields or strong hooks tied to partial events are rejected. Even a valid model response cannot prove real-world retention or video edit-readiness.

## V3 editorial validation (2026-11-08)

The strongest confirmed remaining weakness in V2 was that a candidate's **cliffhanger explanation could cite an earlier dramatic line while a later, mundane camera instruction ended the cut**. V3 evaluates and cites the last completed meaningful dialogue/action beat at the boundary rather than choosing the most dramatic text anywhere in the last five seconds. Automated regression tests assert that the selected ending and ledger match.

V3 also checks for retrospective backstory openings, an opening factual question directly answered shortly afterward, and low-stakes reassurance/mundane opening dialogue. These are general source-text risk checks, **not** footage-based or human-semantic judgments; an editor can override them. The revised private shortlist excludes weak first-hook evidence, explores alternative openings, and retains all rejected source candidates for later review. It does not claim higher viewer conversion.

**New review files** produced by the CLI inside the **private output folder**:

- `14_common_structural_rubric_PRIVATE.json`: the exact same evidence/timing questions applied to A, B and C, with method-by-method coverage and selection-bias warning.
- `15_blinded_editor_scoring_BLANK_PRIVATE.csv`: **empty** rating cells for a real independent reviewer (the method labels are hidden).
- `16_blinded_editor_evidence_PRIVATE.md`: clip-contained source excerpts for reviewing the same anonymous IDs.
- `17_reviewer_unblinding_key_KEEP_SEPARATE_PRIVATE.csv`: keep sealed until the reviewer finishes.
- `18_review_design_manifest.json`: honest declaration that **no actual blind review occurred**.

The submitted prototype should be demonstrated with `examples/synthetic_demo.zip` when publicly hosted. Local full-pack output, viewer HTML, and blinded review evidence contain Kuku's proprietary text and **must remain private**.
