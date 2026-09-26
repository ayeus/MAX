# MAX Rebuild Plan

Status: proposed · 2026-09-26

## Decisions (from owner)
- Brain: **100% local** (Ollama on M4 / 16 GB). No cloud models.
- Tasks: system & apps, inside apps, browser, dev & files.
- Interface: **hotkey push-to-talk** (plus text CLI). No always-on wake word.
- Scope: **new core, reuse proven parts**, stay in Python (+ existing Swift helpers).

## Diagnosis (measured 2026-09-26)
| Symptom | Root cause | Evidence |
|---|---|---|
| Laggy | Plan-everything-upfront prompt on a local model: 8–18 s per plan. Whisper runs on CPU via PyTorch (`fp16=False`). | Timed `Planner.create_plan` on "open Safari" = 12.8 s |
| Wrong/failed plans | `qwen2.5-7b-instruct`, `llama-3.1-8b-instruct`, `mistral-7b` tags are all **gemma2 2.6B** (same ID `8ccf136fdd52`). Configured vision model `qwen3-vl:8b` not installed. | `ollama show` |
| Wake word missed | 3 s chunk → full Whisper transcription → regex for "max". Deaf while transcribing; "Max" often transcribed as "Macs/Mac/maps"; regex also matches "max" mid-sentence. | `voice/assistant.py:163`, `voice/wake.py` |
| "Success" when nothing happened | Regex fast path swallowed a compound command into an app name; verifier reported the bogus app as "verified running". Post-hoc evaluator (1,350 lines) guesses outcomes instead of each action checking its own result. | "open TextEdit and type hello from max" → launched `Textedit And Type Hello From Max`, "verified running" |
| Hard to follow | Entire technical summary is spoken via TTS. | `voice/assistant.py:249` |
| Test pollution | Tests write to the real `~/.max` (audit log, DB). | `~/.max/audit.jsonl` full of test runs |

## Target architecture

```
 [Hotkey held] ──► Swift helper: global hotkey + mic stream
 [Hotkey released] ──► on-device STT (Apple SpeechAnalyzer or whisper.cpp/Metal — bake-off)
                           │ text
                           ▼
                 ┌──── Router (deterministic, <50 ms) ────┐
                 │ splits "A and B then C" into clauses   │
                 │ exact-match known intents → tool calls │
                 └───────┬───────────────────┬────────────┘
                   all matched          anything unmatched
                         │                   ▼
                         │     Agent loop (local LLM, native tool calling,
                         │       JSON-schema constrained, model kept warm)
                         │       observe → pick ONE tool → run → observe → …
                         ▼                   ▼
                 ┌──────────── Tools (typed, small) ────────────┐
                 │ each tool: risk gate → act → CHECK ITS OWN   │
                 │ postcondition → return {done|failed|unsure,  │
                 │ observed_state}                              │
                 └──────────────────────────────────────────────┘
                           ▼
          Short spoken reply ("Done." / "Couldn't find Slack.") + full trace in log
```

Principles:
1. **The model decides one step at a time, looking at real state** — never a blind multi-step plan.
2. **Every tool verifies itself** with a concrete check (exact bundle ID running, AXValue read-back, brightness read-back, file exists, exit code). Status is `done | failed | unsure`; only `done` is ever spoken as success.
3. **Minimize model work**: router handles common commands with zero LLM calls; the LLM sees only relevant tools and a trimmed UI element list (interactive elements with short ids).
4. **Speed budget**: key release → simple command finished **< 1.5 s**; each agent step **< 3 s**.

### Reused as-is or wrapped as tools
`capabilities/accessibility/*` (AX tree, grounding, native mouse), `capabilities/*` operations, `security/*` (risk + audit), `tasks/*` + `event_engine/*`, `memory/*`, Swift helpers in `bin/`, `macos/brightness.py`.

### Replaced / removed at the end
`agent/planner.py`, `agent/replanner.py`, `agent/goal.py`, `verification/evaluator.py`, `agent/intent.py` regex fast path, `voice/wake.py` + chunked wake loop, spoken full summaries.

## Phases (each ends with a measurable, demo-able result)

### Phase A — Ground truth & baseline
- Benchmark suite `benchmarks/tasks.yaml`: ~30 real tasks across the 4 categories, each with an **independent** check (not the tool's own report). Runner records pass/fail + latency.
- Isolate tests from `~/.max` (tmp `MAX_DATA_DIR` fixture).
- Remove mislabeled Ollama tags; pull real candidates; **model bake-off** on the suite (tool-call accuracy + latency), e.g. Qwen3 4B/8B, Qwen2.5 7B, Llama 3.1 8B. Pick default + fast model.
- Exit: baseline numbers for old system recorded.

### Phase B — Voice: push-to-talk
- Swift helper: global hotkey (hold to talk), streams mic while held; cancel with Esc.
- STT bake-off: Apple on-device SpeechAnalyzer vs whisper.cpp (Metal) vs current. Pick fastest accurate.
- Short spoken replies; earcon on start/stop.
- Exit: key release → transcript < 500 ms for a 3 s utterance.

### Phase C — New core: router + tool-calling agent loop
- `core/tools.py`: typed tool definitions wrapping capabilities; each with self-verification.
- `core/router.py`: clause splitter + deterministic intents (open/quit/switch app, brightness, volume, etc.).
- `core/agent.py`: Ollama `/api/chat` with `tools`, `keep_alive`, step cap, cancellation, risk gate, audit.
- New CLI entry uses the new core; old core kept behind a flag until Phase G.
- Exit: "open TextEdit and type hello" works and is truthfully reported; system/apps benchmark ≥ 90 %.

### Phase D — Inside apps
- AX tools: `list_ui(app)` → compact numbered elements; `click(id)`, `type_into(id, text)` (reads value back), `press_key`, `menu(path)`.
- Send/submit actions always HIGH risk → confirm by voice/keypress.
- Exit: Notes / Mail draft / Messages / WhatsApp benchmark tasks pass.

### Phase E — Browser
- Safari/Chrome via AppleScript + JavaScript: open URL, read page text, list links/buttons, click, fill. Deterministic, no screenshots.
- Exit: browser benchmark tasks pass.

### Phase F — Dev & files
- Wrap terminal/filesystem/developer/tasks capabilities as tools; long jobs go to task supervisor + event wait.
- Exit: dev/files benchmark tasks pass.

### Phase G — Cleanup
- Delete replaced modules and their tests; rewrite README/ARCHITECTURE to match reality; drop unused `openai` dependency.

## Open questions / risks
- Local-model tool-calling accuracy on multi-step app tasks is the main risk; mitigated by router, small tool sets, trimmed context, constrained output. Bake-off decides.
- Apps with poor Accessibility support (some Electron apps) may need keyboard-shortcut fallbacks; vision (moondream) stays as last resort only.
