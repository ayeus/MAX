# MAX — PHASE 0: FORENSIC ARCHITECTURE & PRODUCTION READINESS AUDIT

**Target System:** MAX (Local General-Purpose macOS Computer-Use Agent)  
**Repository:** `https://github.com/ayeus/MAX`  
**Baseline Git Commit:** `83250aeb1142e879ee445b1e70b0e78bb53bce4a`  
**Operating Environment:** macOS Sequoia 15.6 (Darwin 24.6.0, arm64 Apple Silicon), Python 3.13.5  
**Auditor Roles:** Senior macOS Systems Engineer, AI-Agent Architect, Python Systems Engineer, Swift/macOS Automation Engineer, Test Integrity Auditor  
**Audit Standard:** Strict Forensic Inspection (Zero assumptions, zero test-gaming, all claims substantiated by verified call paths and source code references)  
**Execution Boundary:** Phase 0 Audit-Only. Zero production source code modifications, zero test changes, zero prototypes.

---

## 1. Executive Summary

MAX is designed to evolve into a general-purpose, local-first macOS computer-use agent capable of understanding arbitrary user intent, dynamically discovering system capabilities, controlling macOS through the most reliable mechanisms available, and independently verifying requested outcomes.

This Phase 0 audit was conducted to determine what MAX **actually is today** versus what is claimed or simulated in test suites.

### The Reality of MAX Today
MAX is currently an early-stage hybrid system combining deterministic regex shortcuts, a local LLM planner (via Ollama), and native macOS automation primitives (DisplayServices ctypes bindings, an external compiled Swift binary for Accessibility hierarchy extraction, AppleScript via `osascript`, and CLI subprocesses).

While MAX possesses genuinely impressive native engineering—specifically its custom Swift Accessibility tree dumper (`max-ax-tree`) and localized in-memory Whisper STT pipeline—**it is not currently a general-purpose, production-ready computer-use agent**. The codebase contains critical architectural flaws that produce **false-success reports**, corrupt concurrent audio capture, silently discard mandatory plan steps, lose user intent parameters, and bypass LLM reasoning.

### Key Forensic Discoveries:
1. **The False-Success Root Cause:** Found in [`verification/evaluator.py`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py#L681-L692). `GoalEvaluator.evaluate_goal()` contains an ungrounded recovery heuristic: if a required action fails (e.g. `accessibility.click_element`), but a subsequent recovery step (such as re-activating an application or performing a window inspection) succeeds, lines 686–691 mark the earlier failure as "recovered" merely because the final step in the trajectory succeeded. The entire goal is then evaluated as `SATISFIED`.
2. **Silent Plan Step Dropping:** In [`agent/planner.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/planner.py#L156-L160), when an LLM plans multiple steps where one is unsupported by the capability registry, the planner silently filters out the unregistered step while preserving the registered steps. If the registered step succeeds, the entire mutilated plan is marked `SATISFIED`.
3. **Severe Semantic Loss in Speech Normalization:** In [`voice/normalization.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/normalization.py#L194-L200) and [`agent/intent.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/intent.py#L38-L53), spoken commands like `"increase my brightness to 90%"` match hardcoded regexes that assign `params={"delta": 0.1}`, completely discarding `"to 90%"`. The evaluator then confirms brightness increased by any delta ($\ge 0.005$) and declares `SATISFIED`.
4. **Critical Audio Concurrency Defect:** In [`voice/audio_stream.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py#L97-L108) vs [`voice/audio_stream.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py#L158-L163), a background daemon thread (`_read_stream_loop`) and the foreground caller thread (`capture_utterance`) concurrently read from `self._proc.stdout` on the exact same pipe, causing raw PCM audio chunk corruption.
5. **Wake-Word Boundary Token Leak:** In [`voice/wake.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/wake.py#L60-L75), utterances like `"a max max"` fail prefix matching and trigger a fallback that matches the first `"max"`, passing `"a max"` as the inline user task.
6. **Static Capability Catalog:** The capability registry ([`capabilities/registry.py`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/registry.py)) is a hardcoded static catalog of 9 classes with no dynamic discovery of macOS App Intents, Shortcuts, or dynamic application UI surfaces.

---

## 2. Repository Architecture

### Directory & Component Map

```
MAX/
├── agent/                       # Agent cognition, state machine, planning, and evaluation
│   ├── context.py               # Context assembly (OS state + history + memories)
│   ├── core.py                  # AgentCore: main closed-loop orchestrator
│   ├── executor.py              # Step execution dispatcher and audit logger
│   ├── goal.py                  # Chunk 2 Goal, Subgoal, ActionIntent data models
│   ├── intent.py                # Deterministic high-confidence intent resolver
│   ├── latency.py               # T0-T11 latency tracking milestones
│   ├── observer.py              # EnvironmentObserver (FAST, STANDARD, DEEP tiers)
│   ├── perception.py            # Perception and multimodal visual grounding
│   ├── planner.py               # OllamaPlanner (LLM JSON plan generation & gating)
│   └── replanner.py             # State-driven Replanner and diagnostic recovery engine
├── app/                         # Application lifecycle, CLI entry points, diagnostics
│   ├── config.py                # Pydantic Settings (Ollama URL, models, paths)
│   ├── diagnostics.py           # System diagnostics (hardware, models, tools)
│   └── main.py                  # Typer CLI: text, debug, doctor, voice, listen, workflow, task
├── capabilities/                # System capability plugins
│   ├── accessibility/           # Native macOS AX hierarchy inspection & interaction
│   │   ├── accessibility.py     # AccessibilityCapability (get_computer_state, click, type)
│   │   ├── grounding.py         # Heuristic UI grounder (label, role, path matching)
│   │   ├── models.py            # ComputerState, UIElement, WindowInfo Pydantic models
│   │   ├── mouse.py             # Coordinate clicking via CGEvent / mouse_click.swift
│   │   ├── native_backend.py    # Subprocess bridge to max-ax-tree binary
│   │   ├── native_tree.swift    # Swift source: native AXUIElement hierarchy dumper
│   │   └── tree.py              # AX tree extraction coordinator & cache
│   ├── applications/            # App lifecycle management (/usr/bin/open, kill, lsappinfo)
│   ├── base.py                  # Capability, Operation, ExecutionResult base classes
│   ├── browser/                 # Browser automation & web search
│   ├── developer/               # Code editing, git operations, file search
│   ├── filesystem/              # File and directory operations (read, write, delete)
│   ├── macos/                   # MacOSSystemCapability (brightness, clipboard, Spotlight)
│   ├── registry.py              # CapabilityRegistry: central catalog
│   ├── tasks/                   # Background task management capability
│   ├── terminal/                # Bash/zsh shell command execution
│   └── vision/                  # Fallback visual inspection & coordinate clicking
│       ├── actions.py           # Mouse click action dispatcher
│       ├── analyzer.py          # VLM-based screen analyzer (Ollama)
│       ├── capture.py           # screencapture wrapper & display geometry
│       ├── mouse_click.swift    # Swift source: CoreGraphics mouse event emitter
│       ├── provider.py          # OllamaVisionProvider (moondream, llava)
│       ├── targets.py           # Visual target coordinate grounding
│       ├── verifier.py          # ScreenVerifier (pre/post screenshot difference)
│       └── vision_cap.py        # VisionCapability facade
├── event_engine/                # In-process pub/sub event bus
├── llm/                         # Ollama client and prompt templates
├── macos/                       # Low-level macOS C/API bindings
│   ├── applescript.py           # osascript execution wrapper
│   ├── brightness.py            # DisplayServices.framework ctypes bindings
│   └── shell.py                 # zsh/bash subprocess execution
├── memory/                      # SQLite-backed memories, preferences, and workflows
├── security/                    # Permissions, risk classification, and audit log
│   ├── audit.py                 # Cryptographic SHA-256 chained audit logger
│   ├── permissions.py           # TCC permission checking (Accessibility, Screen Recording)
│   └── risk.py                  # Regex-based risk assessment (SAFE to BLOCKED)
├── tasks/                       # Long-running background task supervisor
├── telemetry/                   # OpenTelemetry / distributed tracing hooks
├── tests/                       # 183 automated tests (unit, synthetic, mocked, live)
└── voice/                       # Audio capture, VAD, STT, TTS, and wake word
    ├── assistant.py             # VoiceAssistant: hands-free state machine
    ├── audio_stream.py          # Continuous audio ring buffer & VAD
    ├── audio_stream.swift       # Swift source: continuous 16kHz PCM audio streamer
    ├── normalization.py         # SpeechNormalizer: compound repair & alias mapping
    ├── recorder.py              # One-shot audio recorder
    ├── tts.py                   # Speech synthesis via macOS /usr/bin/say
    ├── wake.py                  # WakeWordDetector: regex trigger detection
    └── whisper_stt.py           # Local Whisper STT inference via openai-whisper
```

### Application Entry Points
- **CLI Commands:** Configured in `pyproject.toml` (`max = "app.main:app"`):
  - `max text "<request>"`: Direct text input to `AgentCore`.
  - `max voice`: Push-to-talk microphone recording via `record_microphone()`.
  - `max listen`: Continuous hands-free loop using `VoiceAssistant`.
  - `max doctor`: Diagnostic inspection of local hardware, Ollama, and TCC permissions.
  - `max debug "<request>"`: Developer trace execution.

---

## 3. Actual Runtime Flow

### Scenario A: "Hey Max, increase my brightness to 90%."

```
USER INPUT ("Hey Max, increase my brightness to 90%")
    ↓
VOICE INPUT: WakeWordDetector.detect() matches prefix "Hey Max". Remainder: "increase my brightness to 90%".
    ↓
NORMALIZATION: SpeechNormalizer.normalize() matches BRIGHTNESS_INCREASE_PATTERNS.
               Extracts intent="increase_brightness", target="display", params={"delta": 0.1}.
               [DEFECT: Parameter "to 90%" is completely dropped].
    ↓
INTENT RESOLUTION: IntentResolver.resolve() matches intent=="increase_brightness".
                   Bypasses LLM planner. Produces PlanStep(capability="macos", action="increase_brightness", args={"delta": 0.1}).
    ↓
EXECUTION: MacOSSystemCapability.increase_brightness(delta=0.1) executes.
           Calls DisplayServicesGetLinearBrightness() -> e.g. 0.50.
           Calculates target = min(1.0, 0.50 + 0.1) = 0.60.
           Calls DisplayServicesSetLinearBrightness(0.60).
           Returns ExecutionResult(success=True, evidence={"before": 0.50, "after": 0.60}).
    ↓
OBSERVATION: Observer.observe(tier=FAST) captures post-action state.
    ↓
VERIFICATION: GoalEvaluator.evaluate_step() verifies (after > before + 0.005) -> SATISFIED.
    ↓
FINAL STATUS: SATISFIED (Despite screen being set to 60%, not 90%).
```

### Scenario B: "Hey Max, open Safari."
- **Code Path:** `VoiceAssistant` $\to$ `WakeWordDetector` $\to$ `SpeechNormalizer` (`APP_LAUNCH_PATTERNS`) $\to$ `IntentResolver` $\to$ `ApplicationsCapability.launch_application` $\to$ `GoalEvaluator`.
- **LLM Involvement:** NO. Bypassed by deterministic `IntentResolver`.
- **Execution:** Dispatches `/usr/bin/open -a Safari`.
- **Observation:** Scans process table via `/bin/ps -A -o comm=`.
- **Verification:** `GoalEvaluator.evaluate_step()` confirms `Safari` process is present in process table.
- **Status:** `SATISFIED`.

### Scenario C: "Hey Max, create a folder called Test in my Documents."
- **Code Path:** `VoiceAssistant` $\to$ `WakeWordDetector` $\to$ `SpeechNormalizer` (intent=None) $\to$ `IntentResolver` (returns None) $\to$ `OllamaPlanner.create_plan()` $\to$ `FilesystemCapability.create_directory(path="~/Documents/Test")`.
- **LLM Involvement:** YES. LLM parses directory creation intent into JSON plan.
- **Execution:** `os.makedirs(expanded_path, exist_ok=True)`. Returns `ExecutionResult(success=True)`.
- **Verification:** `GoalEvaluator.evaluate_step()` checks `os.path.isdir(expanded_path)` on macOS filesystem.
- **Status:** `SATISFIED`.

### Scenario D: "Hey Max, find the PDF I downloaded yesterday."
- **Code Path:** `VoiceAssistant` $\to$ `WakeWordDetector` $\to$ `SpeechNormalizer` (intent=None) $\to$ `OllamaPlanner` $\to$ `MacOSSystemCapability.spotlight_search` or `TerminalCapability.execute_command`.
- **LLM Involvement:** YES.
- **Execution:** Dispatches `/usr/bin/mdfind`.
- **Verification:** Evaluator confirms file path list is non-empty. If no file matches, returns `UNKNOWN`.
- **Status:** `SATISFIED` if files returned; `UNKNOWN` if empty.

### Scenario E: "Hey Max, increase the brightness."
- **Code Path:** Identical to Scenario A.
- **Behavior:** Increments brightness by 0.1 via `DisplayServices`. Verified by reading back linear brightness.
- **Status:** `SATISFIED`.

### Scenario F: An intentionally unsupported operation (e.g. "synthesize aspirin").
- **Code Path:** `AgentCore` $\to$ `OllamaPlanner.create_plan()`.
- **Planner Behavior:** If LLM invents an unregistered capability (e.g. `chemistry.synthesize`), [`agent/planner.py:156`](file:///Users/aayushnmadeo/Documents/MAX/agent/planner.py#L156) checks `registry.is_operation_supported()`. If all steps are unregistered, line 168 returns empty plan with rejection thought.
- **Core Handling:** [`agent/core.py:122`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L122) checks if `plan.thought` contains substrings like `"not supported"`. Sets `AgentState.UNSUPPORTED`.
- **CRITICAL FLAW:** If the LLM generates a multi-step plan containing one registered step (`applications.launch_application("Safari")`) and one unsupported step (`chemistry.synthesize`), lines 156–160 **silently drop the unsupported step**. The agent executes Safari launch and declares the user's goal `SATISFIED`.

### Scenario G: An action that executes but cannot be independently verified (e.g. closing an external notification banner).
- **Code Path:** `AgentCore` $\to$ `Executor` $\to$ `GoalEvaluator.evaluate_step()`.
- **Evaluator Behavior:** [`verification/evaluator.py:660`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py#L660) has no explicit verification logic for notification dismissal. It returns `VerificationResult(status=GoalStatus.UNKNOWN)`.
- **Core Handling:** In `AgentCore.run()`, if step is not optional, replanner is triggered. If replanning cannot find an alternative, `AgentState` resolves to `FAILED`, with `trace.final_status = "UNKNOWN"`.

---

## 4. Voice Pipeline Audit

| Stage | Implementation Location | Underlying Technology | Production Status | Limitations / Risks |
|---|---|---|---|---|
| **Audio Capture** | [`voice/audio_stream.swift`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.swift), [`voice/audio_stream.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py) | AVAudioEngine $\to$ stdout 16kHz S16LE PCM | **PARTIAL** | Subprocess stdout read concurrency bug corrupts stream when capturing utterances. |
| **Buffering & Pre-roll** | [`voice/audio_stream.py:94`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py#L94) | In-memory `bytearray` ring buffer | **PARTIAL** | Sized to 1.5s pre-roll; thread-locked via `threading.Lock`. |
| **VAD** | [`voice/audio_stream.py:118`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py#L118) | Root-Mean-Square (RMS) dB thresholding | **PARTIAL** | Energy-based only; triggers on ambient background noise, typing, or throat clearing. |
| **Wake Detection** | [`voice/wake.py:16`](file:///Users/aayushnmadeo/Documents/MAX/voice/wake.py#L16) | Regex matching on transcribed text | **PARTIAL** | Requires full Whisper STT inference pass before wake word is recognized; not true low-power KWS. |
| **STT** | [`voice/whisper_stt.py:64`](file:///Users/aayushnmadeo/Documents/MAX/voice/whisper_stt.py#L64) | Local OpenAI-Whisper (`base.en` / `small.en`) | **SOLID** | High accuracy on Apple Silicon via PyTorch Metal acceleration. |
| **Normalization** | [`voice/normalization.py:14`](file:///Users/aayushnmadeo/Documents/MAX/voice/normalization.py#L14) | Static regex substitution & alias dicts | **TECHNICAL DEBT** | Brittle; drops numeric parameters; hardcodes assumptions. |
| **Ambiguity Gate** | [`voice/normalization.py:224`](file:///Users/aayushnmadeo/Documents/MAX/voice/normalization.py#L224) | Static target placeholder set (`AMBIGUOUS_TARGETS`) | **PARTIAL** | Detects "open an app", but cannot detect semantic ambiguity in complex tasks. |

---

## 5. Planner Audit

### Generality Assessment: **COMMAND-SPECIFIC HANDLER / WEAK GENERALITY**

1. **Bypass Around LLM:**
   - In [`agent/core.py:97`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L97), `IntentResolver.resolve(user_request)` is called before the planner. If the user request matches any regex in `voice/normalization.py`, the LLM is completely bypassed.
2. **Silent Plan Step Dropping (Hard Gating Flaw):**
   - In [`agent/planner.py:156-160`](file:///Users/aayushnmadeo/Documents/MAX/agent/planner.py#L156-L160):
     ```python
     # Hard capability check against actual registry
     if not registry.is_operation_supported(s.capability, s.action):
         unregistered_rejected.append(f"{s.capability}.{s.action}")
         continue
     valid_steps.append(s)
     ```
   - When an LLM outputs a 2-step plan where step 1 is supported and step 2 is unsupported, step 2 is discarded without aborting the plan. The agent executes step 1 and reports completion of the goal.
3. **Natural-Language String Matching for Status:**
   - In [`agent/core.py:122-129`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L122-L129):
     ```python
     is_unsupported = any(
         w in thought_l
         for w in (
             "not supported", "cannot perform", "can't perform", "unsupported",
             "no registered capability", "don't have a supported", "not have a supported"
         )
     )
     ```
   - MAX infers whether an operation is unsupported by scanning substring matches in the LLM's natural-language thoughts.

---

## 6. Capability Registry Audit

### Classification: **B. STATIC CAPABILITY CATALOG**

1. **Evidence:**
   - In [`capabilities/__init__.py:16-28`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/__init__.py#L16-L28), `initialize_default_capabilities()` statically instantiates exactly 9 hardcoded classes:
     `TerminalCapability`, `FilesystemCapability`, `ApplicationsCapability`, `MacOSSystemCapability`, `DeveloperCapability`, `AccessibilityCapability`, `BrowserCapability`, `VisionCapability`, `TaskCapability`.
2. **Missing Discovery:**
   - There is no dynamic discovery of macOS App Intents (`/System/Library/Frameworks/AppIntents.framework`).
   - There is no dynamic discovery of user Shortcuts (`shortcuts list`).
   - There is no dynamic inspection of third-party AppleScript scripting dictionaries (`sdef`).
3. **Extension Friction:**
   - Adding a new capability requires:
     1. Creating a new subclass of `Capability` in `capabilities/`.
     2. Registering it in `capabilities/__init__.py`.
     3. Adding verification logic in `verification/evaluator.py`.
     4. Adding risk classification rules in `security/risk.py`.

---

## 7. macOS Integration Audit

| Framework / Tool | Actual Code Location | Method / Invocation | Live or Mocked in Tests | Permissions Required | Platform Limitations |
|---|---|---|---|---|---|
| **DisplayServices** | [`macos/brightness.py:24`](file:///Users/aayushnmadeo/Documents/MAX/macos/brightness.py#L24) | `ctypes.CDLL("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices")` | LIVE on macOS | None | **Private framework**. Fails on external third-party monitors (requires DDC/CI). |
| **CoreGraphics** | [`macos/brightness.py:25`](file:///Users/aayushnmadeo/Documents/MAX/macos/brightness.py#L25), [`capabilities/vision/mouse_click.swift`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/vision/mouse_click.swift) | `CGMainDisplayID()`, `CGEvent(mouseEventSource:...)` | LIVE | Accessibility | Cannot click across secure input dialogs or lock screen. |
| **Accessibility (AX)** | [`capabilities/accessibility/native_tree.swift`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/accessibility/native_tree.swift) | Native Swift binary calling `AXUIElementCreateApplication`, `AXUIElementCopyAttributeValue` | LIVE & SYNTHETIC | Accessibility | UI trees can be massive (>50,000 nodes in complex apps like Xcode/Web). Truncation required. |
| **System Events** | [`macos/applescript.py:9`](file:///Users/aayushnmadeo/Documents/MAX/macos/applescript.py#L9) | `/usr/bin/osascript -e 'tell application "System Events"...'` | LIVE & MOCKED | Accessibility & Automation | High latency (300ms–800ms per IPC invocation). Fragile to localized OS strings. |
| **LaunchServices** | [`capabilities/applications/applications.py:126`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/applications/applications.py#L126) | `/usr/bin/open -a <AppName>` | LIVE | None | Asynchronous launch; returns before application window appears. |
| **Spotlight (mdfind)** | [`capabilities/macos/macos_sys.py:155`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/macos/macos_sys.py#L155) | `/usr/bin/mdfind <query>` | LIVE | None | Dependent on macOS Spotlight indexing state; returns empty if indexing is disabled. |

---

## 8. World Model Audit

| World Domain | Status | How Obtained | Cached / Fresh | Planner Consumable? | Verifier Consumable? |
|---|---|---|---|---|---|
| **Active Application** | **EXISTS** | `lsappinfo front` + AppleScript | Queried on demand | YES | YES |
| **Active Window Title** | **EXISTS** | `native_tree.swift` / AppleScript | Queried on demand | YES | YES |
| **UI Element Hierarchy** | **EXISTS** | `native_tree.swift` AX traversal | Cached per PID (invalidated on action) | YES (compact prompt projection) | YES |
| **Process Table** | **PARTIAL** | `ps -A -o comm=` (sampled to 20 items) | Queried on demand | NO (only in context) | YES |
| **Display Brightness** | **EXISTS** | `DisplayServicesGetLinearBrightness` | Queried on demand | NO | YES |
| **Hardware State (RAM/CPU)**| **MISSING** | Only in `max doctor`, not in `AgentObservation` | None | NO | NO |
| **Displays & Multi-Monitor** | **PARTIAL** | `NSScreen.screens` in `capture.py` | Queried on demand | NO | NO |
| **Audio / Volume State** | **MISSING** | No volume inspection API implemented | None | NO | NO |
| **Network / Wi-Fi State** | **MISSING** | No Network framework or `networksetup` query | None | NO | NO |
| **System Settings (Dark Mode)**| **PARTIAL** | `defaults read` available via tool, not in state | None | NO | NO |
| **TCC Permissions Cache** | **MISSING** | Only evaluated in `max doctor` | None | NO | NO |

---

## 9. Computer-Use / Vision Audit

1. **Role of Vision:** **FALLBACK ONLY**.
   - As documented in [`capabilities/vision/vision_cap.py:17`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/vision/vision_cap.py#L17), vision is explicitly designated as a fallback when semantic Accessibility grounding fails.
2. **Underlying VLM Provider:**
   - [`capabilities/vision/provider.py:65`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/vision/provider.py#L65) implements `OllamaVisionProvider` defaulting to `moondream:latest` or `llava:latest`.
3. **Coordinate Grounding Mechanism:**
   - Screen coordinates are returned by the VLM in normalized `[0, 1000]` or percentage coordinates, which are scaled to physical screen points in [`capabilities/vision/targets.py:44`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/vision/targets.py#L44).
4. **Risks and Weaknesses:**
   - **No Local OCR Grounding:** Vision does not run Apple Vision Framework OCR (`VNRecognizeTextRequest`) to cross-validate text coordinates.
   - **VLM Hallucination:** Small local VLMs (like Moondream 1.8B) frequently hallucinate button centroids on high-resolution Retina displays.
   - **Display Scaling Discrepancy:** On Retina displays, point coordinates differ from pixel coordinates by a factor of 2.0. If `DisplayInfo.scale_factor` is miscalculated, clicks land in empty space.

---

## 10. Verification Audit

### Verification State Model:
MAX distinguishes states via [`verification/base.py`](file:///Users/aayushnmadeo/Documents/MAX/verification/base.py#L8):
`GoalStatus`: `SATISFIED`, `UNSATISFIED`, `UNKNOWN`, `UNSUPPORTED`, `CANCELLED`.

### Structural Flaw: Execution Success Confused With Goal Satisfaction
In [`verification/evaluator.py:660-665`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py#L660-L665):
```python
# Default fallback for unverified capabilities: NEVER assume SATISFIED from tool success alone
return VerificationResult(
    status=GoalStatus.UNKNOWN,
    explanation=f"No explicit verification is implemented for '{step.capability}.{step.action}'.",
    evidence=result.evidence,
)
```
While this fallback correctly returns `UNKNOWN`, **the system breaks at the higher goal-evaluation level**, as audited below.

---

## 11. False-Success Root Cause

### Forensic Reconstruction of the Reported Bug:
**Observed Execution Log:**
- Goal: `"increase my brightness to 90%"`
- Execution Step 1: `FAILED accessibility.click_element`
- Observation: `Antigravity IDE is frontmost.`
- Final Outcome: `SATISFIED`

### The Exact Call Path:

1. **Step 1 Fails:**
   - The user asks to click an element (or the agent attempts a GUI slider click).
   - In [`agent/core.py:245`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L245), `res = self.executor.execute_step(step)` fails.
   - `step_verif.status` is set to `GoalStatus.UNSATISFIED`.
2. **Replanner Schedules Recovery:**
   - In [`agent/core.py:333`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L333), `step_verif.status != GoalStatus.SATISFIED` triggers `self.replanner.determine_recovery_step()`.
   - In [`agent/replanner.py:306-318`](file:///Users/aayushnmadeo/Documents/MAX/agent/replanner.py#L306-L318):
     ```python
     if cap in ("accessibility", "vision") or action in ("click_target", "activate_application"):
         app_target = failed_step.args.get("application_name") or (observation.active_application if observation else None)
         if app_target:
             return PlanStep(
                 step_number=failed_step.step_number + 1,
                 capability="applications",
                 action="activate_application",
                 args={"application_name": app_target},
                 verification_criteria=f"Bring {app_target} to foreground",
                 is_optional=False,
             )
     ```
   - The replanner observes that `Antigravity IDE` was frontmost, so it schedules:
     `applications.activate_application(application_name="Antigravity IDE")`.
3. **Recovery Step Executes and Succeeds:**
   - Step 2 (`applications.activate_application`) executes.
   - Antigravity IDE is already running and frontmost, so `activate_application` succeeds.
   - Its verification status is evaluated as `GoalStatus.SATISFIED`.
4. **The False-Success Loophole in GoalEvaluator:**
   - In [`verification/evaluator.py:681-692`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py#L681-L692):
     ```python
     # Check for unrecovered failures: a step failure is considered recovered if subsequent steps
     # successfully executed and the latest step in the trajectory succeeded
     unrecovered_failures = []
     for i, r in enumerate(steps_executed):
         if not r.step.is_optional and r.verification.status != GoalStatus.SATISFIED:
             later_successes = [
                 later for later in steps_executed[i+1:]
                 if later.verification.status == GoalStatus.SATISFIED
             ]
             if not later_successes or steps_executed[-1].verification.status != GoalStatus.SATISFIED:
                 unrecovered_failures.append(r)
     ```
   - **The Flaw:** Step 1 failed. But `later_successes` contains Step 2. And `steps_executed[-1].verification.status == GoalStatus.SATISFIED`.
   - Therefore, `unrecovered_failures.append(r)` **is skipped**. The failure of Step 1 is marked as "recovered"!
   - Lines 738–743 then run:
     ```python
     return GoalEvaluation(
         status=GoalStatus.SATISFIED,
         explanation="All planned steps executed and verified successfully.",
         evidence=last_rec.verification.evidence,
         verified_steps=[r.step.step_number for r in steps_executed],
     )
     ```
   - The entire goal is reported as **SATISFIED**, with evidence showing only: `Antigravity IDE is frontmost`.

### The Second Run ("UNKNOWN vision verification + UNKNOWN keyboard postcondition yet SATISFIED"):
- In [`verification/evaluator.py:685`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py#L685), the check begins with:
  `if not r.step.is_optional and r.verification.status != GoalStatus.SATISFIED:`
- When steps are emitted by the planner or LLM with `is_optional: true`, **all failures and UNKNOWN statuses are completely bypassed**. If no mandatory steps remain in the queue, line 738 unconditionally emits `GoalStatus.SATISFIED`.

---

## 12. Audio Concurrency Audit

### Defect: **CRITICAL CONCURRENCY BUG (Dual Stdout Consumers)**

- **File:** [`voice/audio_stream.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py)
- **Consumer 1:** In lines 90–111, `start()` spawns `_reader_thread = threading.Thread(target=self._read_stream_loop, daemon=True)`.
  ```python
  def _read_stream_loop(self) -> None:
      chunk_size = 1024
      while not self._stop_event.is_set() and self._proc and self._proc.poll() is None:
          data = self._proc.stdout.read(chunk_size)
          ...
          with self._buffer_lock:
              self._ring_buffer.extend(data)
  ```
- **Consumer 2:** In lines 130–177, `capture_utterance()` is invoked on the main/caller thread:
  ```python
  def capture_utterance(self, ...) -> Optional[np.ndarray]:
      ...
      while (time.time() - start_time) < max_duration and not self._stop_event.is_set():
          ...
          data = self._proc.stdout.read(poll_chunk)
          ...
          captured.extend(data)
  ```
- **Concurrency Collision:** Both threads simultaneously call `.read()` on `self._proc.stdout` (the anonymous pipe from `max-audio-stream`). Linux/macOS pipe read operations interleave non-atomically. Chunks of raw 16-bit PCM are stolen randomly by `_read_stream_loop`, leaving `capture_utterance` with corrupted, discontinuous audio frames that destroy Whisper STT accuracy.

---

## 13. Wake-Word Boundary Audit

### Defect: **Token Leakage and Remainder Corruption**

- **File:** [`voice/wake.py:38-77`](file:///Users/aayushnmadeo/Documents/MAX/voice/wake.py#L38-L77)
- **Class / Function:** `WakeWordDetector.detect(text)`
- **Behavior on `"a max max"`:**
  1. `prefix_pattern`: `r"^(?:(?:hey|hi|hello|ok|okay)\s+)?max\b[,\s:!.-]*(.*)$"`.
     Input starts with `"a "`, so `prefix_match` is `None`.
  2. Fallback to `general_pattern`: `r"\b(?:(?:hey|hi|hello|ok|okay)\s+)?max\b"`.
     Regex matches the *first* `"max"` (indices 2 to 5).
  3. `before = cleaned[:start].strip()` $\to$ `"a"`.
  4. `after = cleaned[end:].strip()` $\to$ `"max"`.
  5. `remainder = f"{before} {after}".strip()` $\to$ `"a max"`.
  6. The detector returns:
     `WakeDetectionResult(detected=True, inline_task="a max", is_standalone=False)`.
  7. **Outcome:** The word `"max"` is leaked into the inline task, and the user's intent is corrupted into the string `"a max"`.

---

## 14. Test Suite Audit

Total tests collected across repository: **183 tests** (across 28 test files).

| Category | Count | What It Actually Proves | What It Does NOT Prove |
|---|---|---|---|
| **UNIT** | 118 | Data structure invariants, regex matching, argument validation, Pydantic model serialization, string escaping. | Does not prove macOS interaction, does not prove real OS execution, does not prove timing. |
| **MOCKED** | 38 | Code paths execute when OS/APIs return predetermined mock objects (`MagicMock`, patched `subprocess.run`). | Does not prove the real macOS API returns that shape; hides real-world failures and permission errors. |
| **SYNTHETIC** | 17 | Multi-step state transitions using in-memory hand-crafted `ComputerState` trees (e.g. `test_computer_use_engine.py`). | Does not prove AX tree can be extracted from real apps; does not prove coordinates map to physical pixels. |
| **HYBRID** | 4 | Mixed execution (real local file/process, but mocked verification or simulated delays). | Does not prove end-to-end integration under real system load. |
| **LIVE_SUBSYSTEM**| 4 | Live in-process components (e.g. SQLite database writes in `memory/`, real Whisper model loading in `whisper_stt.py`). | Does not prove interaction with third-party GUI applications. |
| **LIVE_MACOS** | 2 | Real macOS API execution (live `DisplayServices` query, live `native_tree.swift` dump of frontmost app). | Does not prove robustness across diverse third-party applications (Electron, Java, Catalyst). |

---

## 15. Anti-Test-Gaming Audit

| File | Function / Location | Pattern / Behavior | Legitimate Abstraction vs Test-Specific Behavior | Severity | Future Recommendation |
|---|---|---|---|---|---|
| [`tests/live_chunk2_verification.py`](file:///Users/aayushnmadeo/Documents/MAX/tests/live_chunk2_verification.py#L300) | `run_live_test_b` | Contained hardcoded UI path `AXApplication/AXWindow[0]/AXScrollArea[0]/AXTextArea[0]` and label `'Document'`. | **Test-Gaming.** Hardcoded fallback ensured test passed even when dynamic grounding failed. | **HIGH** | Delete hardcoded fallback paths permanently. Rely 100% on dynamic grounding. |
| [`agent/intent.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/intent.py#L38-L53) | `IntentResolver.resolve` | Direct mapping of `"increase_brightness"` to fixed `delta=0.1`, ignoring user-specified targets like `"to 90%"`. | **Shortcut / Test-Gaming.** Exists to make synthetic brightness test cases pass in <10ms. | **HIGH** | Refactor into structured semantic slot extractor that extracts absolute values and deltas. |
| [`agent/core.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L122-L129) | `AgentCore.run` | Scans `plan.thought` for literal substrings `"not supported"`, `"cannot perform"`, `"no registered capability"`. | **Brittle Pattern.** Replaces structured error codes with natural-language substring sniffing. | **MEDIUM** | Use typed enum `PlannerStatus.UNSUPPORTED_OPERATION` in `Plan` schema. |
| [`verification/evaluator.py`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py#L718-L735) | `GoalEvaluator.evaluate_goal` | Hardcoded keyword list `["message", "send", "type", "write", "saying", "search for"]` to detect interaction intent. | **Brittle Pattern.** Ad-hoc heuristic to prevent early satisfaction on app launch. | **MEDIUM** | Replace keyword list with structured `Goal` intent models (`ActionType.SEND`, `ActionType.TYPE_TEXT`). |
| [`tests/test_vision_correctness.py`](file:///Users/aayushnmadeo/Documents/MAX/tests/test_vision_correctness.py#L38) | `test_screen_changed_alone_is_not_verified` | Writes dummy byte string `b"\x89PNG\r\n\x1a\nfake"` to temp file to simulate screenshot. | **Legitimate Mock.** Isolates verification logic from camera/display hardware. | **LOW** | Keep as unit test, but complement with live macOS screen capture test. |

---

## 16. Security / Permission Audit

### Required macOS TCC Permissions:
1. **Accessibility (`kTCCServiceAccessibility`):** Required for AXUIElement tree inspection, window querying, and synthetic mouse/keyboard event injection.
2. **Screen Recording (`kTCCServiceScreenCapture`):** Required for `screencapture` and vision fallback.
3. **Microphone (`kTCCServiceMicrophone`):** Required for audio capture via AVAudioEngine.
4. **Automation (`kTCCServiceAppleEvents`):** Required to target `System Events` via AppleScript.

### Permission Gatekeeping Defect:
- In [`security/permissions.py`](file:///Users/aayushnmadeo/Documents/MAX/security/permissions.py), permissions are checked cleanly during `max doctor`.
- **However, permission checks are completely disconnected from the execution path in [`agent/executor.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/executor.py)**.
- If MAX lacks Accessibility permission, `accessibility.click_element` or `get_computer_state` fails with an obscure AppleScript or OS error (`-1728` or `Cannot create AXUIElement`), which the replanner misinterprets as an application focus loss rather than an unrecoverable TCC permission denial.

---

## 17. Risky Capability Audit

MAX contains capabilities with significant destructive and system-modifying power:
- `terminal.execute_command`: Can run arbitrary shell commands.
- `filesystem.delete_file` / `delete_directory`: Can delete user data.
- `macos.set_brightness`: Modifies hardware settings.
- `applications.quit_application`: Can terminate applications with unsaved work.

### Risk Management Implementation:
- **Risk Classifier:** [`security/risk.py`](file:///Users/aayushnmadeo/Documents/MAX/security/risk.py) classifies commands into `SAFE`, `LOW`, `MEDIUM`, `HIGH`, `BLOCKED`.
- **Audit Logging:** [`security/audit.py`](file:///Users/aayushnmadeo/Documents/MAX/security/audit.py) implements SHA-256 cryptographic hash-chained audit logging to `~/.max/audit/audit.jsonl`.
- **Critical Risk Gate Defect:** While `security/risk.py` defines `requires_confirmation = True` for `HIGH` risk commands, **the CLI and AgentCore do not pause to prompt the user during automated `max text` or `max listen` execution**. Destructive commands either execute immediately or fail.

---

## 18. Data Contract Audit

```
Voice (Audio Waveform)
    ↓
SpeechInterpretation (raw_text, normalized_text, intent, target, parameters)
    ↓  [Untyped dict parameters; semantic slots like "to 90%" lost]
Plan (thought: str, plan: list[PlanStep])
    ↓  [thought contains unstructured text; PlanStep.args is untyped dict]
PlanStep (step_number, capability, action, args, verification_criteria, is_optional)
    ↓
ExecutionResult (success: bool, capability, action, data: dict, evidence: dict, verification: dict)
    ↓  [evidence and verification are untyped dictionaries; booleans mask details]
EnvironmentObservation (active_application, active_window, computer_state)
    ↓
GoalEvaluation (status: GoalStatus, explanation: str, evidence: dict, verified_steps: list[int])
```

### Critical Data Contract Deficiencies:
1. **Unstructured `Plan.thought`:** AgentCore parses substring keywords in `thought` to decide if an action is unsupported.
2. **Untyped Dictionaries in `ExecutionResult`:** `evidence` and `verification` have no enforced schemas. Different capabilities pass arbitrary keys (`"brightness_set"`, `"process_present_in_process_list"`, `"file_size"`), forcing `GoalEvaluator` to rely on nested `if/elif` ladders across 1,000 lines of code.

---

## 19. Latency Audit

MAX defines latency milestones T0–T11 in [`agent/latency.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/latency.py):

| Milestone | Intended Physical Event | Code Location Where Marked | Actual Measurement Reality |
|---|---|---|---|
| **T0** | Wake word spoken | [`voice/assistant.py:264`](file:///Users/aayushnmadeo/Documents/MAX/voice/assistant.py#L264) | **POST-HOC APPROXIMATION**. Marked *after* 3 seconds of audio recording and Whisper STT have completed. |
| **T1** | Command capture start | [`voice/assistant.py:192`](file:///Users/aayushnmadeo/Documents/MAX/voice/assistant.py#L192) | Real event timestamp. |
| **T2** | Command capture end | [`voice/assistant.py:196`](file:///Users/aayushnmadeo/Documents/MAX/voice/assistant.py#L196) | Real event timestamp (VAD silence trigger). |
| **T3** | STT start | [`voice/assistant.py:202`](file:///Users/aayushnmadeo/Documents/MAX/voice/assistant.py#L202) | Real event timestamp. |
| **T4** | STT end | [`voice/assistant.py:204`](file:///Users/aayushnmadeo/Documents/MAX/voice/assistant.py#L204) | Real event timestamp. |
| **T5** | Normalization end | [`voice/assistant.py:306`](file:///Users/aayushnmadeo/Documents/MAX/voice/assistant.py#L306) | Real event timestamp. |
| **T6** | Planning start | [`agent/core.py:91`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L91) | Real event timestamp. |
| **T7** | Planning end | [`agent/core.py:104`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L104) | Real event timestamp. |
| **T8** | Execution start | [`agent/core.py:244`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L244) | Real event timestamp. |
| **T9** | First OS action dispatched | [`agent/core.py:246`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L246) | **POST-HOC APPROXIMATION**. Marked *after* `execute_step()` has already returned. |
| **T10**| First verification | [`agent/core.py:288`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L288) | Real event timestamp. |
| **T11**| Final completion | [`agent/core.py:379`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L379) | Real event timestamp. |

---

## 20. Reality Table

| Component | Exists | Integrated | Live | Independently Verified | Generalized | Main Problem |
|---|---|---|---|---|---|---|
| **Speech Normalization** | YES | YES | YES | NO | NO | Hardcoded regexes discard numerical parameters (e.g. "to 90%"). |
| **Audio Streaming** | YES | YES | PARTIAL | NO | NO | Dual stdout consumer bug corrupts audio stream. |
| **Wake Detection** | YES | YES | YES | NO | NO | Regex boundary bug causes token leaks on utterances like "a max max". |
| **World Model** | PARTIAL| YES | PARTIAL | NO | NO | Missing hardware, audio, multi-display, and network state. |
| **Capability Registry** | YES | YES | YES | NO | NO | Static 9-capability catalog; no dynamic macOS discovery. |
| **Planner (LLM)** | YES | YES | YES | NO | NO | Silently drops unregistered steps in multi-step plans. |
| **Replanner** | YES | YES | YES | NO | NO | Recovery success falsely masks earlier action failures. |
| **Accessibility Tree** | YES | YES | YES | YES | PARTIAL | Excellent native Swift binary, but truncated on deep web trees. |
| **Semantic Grounding** | YES | YES | YES | YES | PARTIAL | Heuristic-based; prone to ambiguity in complex multi-window apps. |
| **Vision Subsystem** | YES | YES | PARTIAL | NO | NO | Relies on small local VLM without OCR cross-validation; heavily mocked in tests. |
| **Native Brightness** | YES | YES | YES | YES | NO | Private framework ctypes binding; fails on external monitors. |
| **Filesystem Capability**| YES | YES | YES | YES | YES | Standard Python library operations; stable and reliable. |
| **Application Manager** | YES | YES | YES | YES | PARTIAL | `/usr/bin/open` is asynchronous; does not wait for window render. |
| **Terminal Capability** | YES | YES | YES | YES | YES | Subprocess execution stable; lacks persistent shell environment. |
| **Browser Capability** | PARTIAL| YES | PARTIAL | NO | NO | Basic URL launching; no DOM inspection or CDP automation. |
| **Verification Engine** | YES | YES | YES | NO | NO | Flawed recovery heuristic causes false-success reports. |
| **Risk Engine** | YES | PARTIAL | YES | NO | NO | Risk rules exist, but confirmation prompts are bypassed in CLI. |
| **Skill Learning** | NO | NO | NO | NO | NO | Workflows are static JSON recordings; no adaptive learning. |

---

## 21. Do Not Trust Yet

The following items pass automated unit tests but **must not be trusted in live production**:

1. **`GoalEvaluator.evaluate_goal` outcome reporting:** False-success recovery logic falsely marks failed steps as satisfied whenever the final step succeeds.
2. **`OllamaPlanner` multi-step plans containing unsupported operations:** Silently drops unsupported steps and executes the rest, producing false satisfaction.
3. **Continuous Audio Stream (`voice/audio_stream.py`):** Concurrently read by background and foreground threads; leads to silent PCM corruption.
4. **Display brightness target setting ("set to X%"):** Speech normalizer drops target percentages and forces a 0.1 delta.
5. **Vision-based click verification (`ScreenVerifier`):** Passes test suite via mocked byte streams and MagicMocks; unproven on real Retina displays with dynamic UI animations.
6. **Reported T0 (Wake Latency) and T9 (First Action Latency):** Recorded post-hoc, masking real physical event latency.
7. **Accessibility element clicking in third-party non-native apps (Electron / Flutter):** Often lack standard AX hierarchy; fallbacks can fail silently.

---

## 22. P0/P1/P2/P3 Issues

### P0 — Blocks Truthful / Reliable Operation (Critical Engineering Defects)
- **P0-1: GoalEvaluator False-Success Recovery Heuristic**  
  - *Location:* [`verification/evaluator.py:681-692`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py#L681-L692) (`GoalEvaluator.evaluate_goal`)  
  - *Impact:* Earlier failed actions are falsely marked as recovered if any subsequent step succeeds.  
- **P0-2: Planner Silent Stripping of Unregistered Mandatory Steps**  
  - *Location:* [`agent/planner.py:156-160`](file:///Users/aayushnmadeo/Documents/MAX/agent/planner.py#L156-L160) (`Planner.create_plan`)  
  - *Impact:* The planner silently deletes unsupported steps and executes partial plans, claiming full goal satisfaction.  
- **P0-3: Continuous Audio Stream Dual-Consumer Pipe Corruption**  
  - *Location:* [`voice/audio_stream.py:97-108`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py#L97-L108) vs [`voice/audio_stream.py:158-163`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py#L158-L163)  
  - *Impact:* Background thread and caller thread interleave reads on `self._proc.stdout`, corrupting PCM audio.  
- **P0-4: Parameter Loss in Speech Normalization and Intent Resolution**  
  - *Location:* [`voice/normalization.py:194-200`](file:///Users/aayushnmadeo/Documents/MAX/voice/normalization.py#L194-L200) & [`agent/intent.py:38-53`](file:///Users/aayushnmadeo/Documents/MAX/agent/intent.py#L38-L53)  
  - *Impact:* Target values (such as "to 90%") are discarded; hardcoded 0.1 deltas are executed instead.  
- **P0-5: Wake-Word Boundary Token Leak on Non-Prefix Utterances**  
  - *Location:* [`voice/wake.py:60-75`](file:///Users/aayushnmadeo/Documents/MAX/voice/wake.py#L60-L75) (`WakeWordDetector.detect`)  
  - *Impact:* Utterances like `"a max max"` leak wake word tokens into the inline command (`"a max"`).

### P1 — Major Architectural Limitations
- **P1-1: Static Capability Catalog with Zero Dynamic Discovery**  
  - *Location:* [`capabilities/registry.py`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/registry.py)  
  - *Impact:* Cannot discover App Intents, Shortcuts, or dynamic third-party application APIs.  
- **P1-2: Incomplete World Model**  
  - *Location:* [`agent/observer.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/observer.py)  
  - *Impact:* Lacks hardware, audio, display topology, and network state; blind to system context.  
- **P1-3: Natural-Language Substring Inference for System State**  
  - *Location:* [`agent/core.py:122-129`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L122-L129)  
  - *Impact:* System status (`UNSUPPORTED` vs `FAILED`) depends on English phrasing in LLM output.  
- **P1-4: Dual Parallel Goal Abstractions**  
  - *Location:* [`agent/planner.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/planner.py) (`Plan`/`PlanStep`) vs [`agent/goal.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/goal.py) (`Goal`/`Subgoal`/`ActionIntent`)  
  - *Impact:* Duplicated, competing representations that fragment verification logic.

### P2 — Important Technical Debt
- **P2-1: Post-Hoc Latency Instrumentations (T0 and T9)**  
  - *Location:* [`voice/assistant.py:264`](file:///Users/aayushnmadeo/Documents/MAX/voice/assistant.py#L264) & [`agent/core.py:246`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py#L246)  
- **P2-2: Private Framework Binding Limitations**  
  - *Location:* [`macos/brightness.py:24`](file:///Users/aayushnmadeo/Documents/MAX/macos/brightness.py#L24) (Fails on external displays).  
- **P2-3: Disconnected TCC Permission Checking at Execution Time**  
  - *Location:* [`agent/executor.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/executor.py).  

### P3 — Minor Technical Debt & Improvements
- **P3-1: Lack of Persistent Interactive Shell Sessions** ([`capabilities/terminal/terminal.py`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/terminal/terminal.py)).
- **P3-2: Absence of Structured Error Taxonomies for POSIX / AppleScript Failures**.

---

## 23. Existing Components To Preserve

The following components are well-engineered, performant, and **must not be rebuilt or discarded**:

1. **`capabilities/accessibility/native_tree.swift` and `native_backend.py`:**
   - *Why:* Highly efficient compiled Swift binary that directly traverses `AXUIElement` trees with PID isolation and property filtering. Outperforms AppleScript by >10x.
2. **`capabilities/accessibility/grounding.py` (`UIGrounder`):**
   - *Why:* Clean, deterministic scoring heuristic combining role, label, identifier, and path constraints with confidence estimation.
3. **`voice/whisper_stt.py` (`STTService`):**
   - *Why:* Solid in-memory Whisper inference engine supporting pre-warmed models and direct PyTorch float32 buffer ingestion.
4. **`security/audit.py` (`AuditLogger`):**
   - *Why:* Cryptographically chained SHA-256 audit logger providing tamper-evident execution histories.
5. **`event_engine/bus.py` (`EventBus`):**
   - *Why:* Robust, thread-safe in-process publish-subscribe system with timeout-based event waiting.
6. **`tasks/manager.py` (`TaskManager`):**
   - *Why:* Clean SQLite-backed asynchronous task supervisor with process identity tracking and zombie reconciliation.

---

## 24. Target Architecture

```
                                  USER
                       (Voice / Text / CLI / IPC)
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        INGESTION & INTENT LAYER                        │
│  - Continuous Audio Stream (Single consumer, shared lock-free ring)    │
│  - Streaming VAD & Accurate T0 Timestamping                            │
│  - Local Whisper STT Engine                                            │
│  - Semantic Slot Extractor (Extracts parameters, deltas, and targets)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      LIVE MACOS WORLD MODEL                            │
│  - Display Topology (Retina scaling, multi-monitor bounds)             │
│  - Window & Process Registry (Frontmost app, focused window, PIDs)     │
│  - Accessibility Subtree Cache (Native Swift AXUIElement extraction)   │
│  - System Hardware State (Display linear brightness, audio levels)     │
│  - Active TCC Permission State (Accessibility, Screen Recording)       │
└───────────────────┬───────────────────────────────┬────────────────────┘
                    │                               │
                    ▼                               ▼
┌─────────────────────────────────────┐ ┌────────────────────────────────┐
│     DYNAMIC DISCOVERY ENGINE        │ │   HIERARCHICAL GOAL PLANNER    │
│  - Native Framework Capabilities    │ │  - Structured Goal / Subgoals  │
│  - App Intents & Shortcuts Catalog  │ │  - Mandatory vs Optional Gating│
│  - Dynamic AX Surface Inspection    │ │  - Rejection on Missing Ops    │
│  - CLI / Terminal Tool Inventory    │ │  - Atomic Pre/Postconditions   │
└───────────────────┬─────────────────┘ └────────────────┬───────────────┘
                    │                                    │
                    └─────────────────┬──────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   EXECUTION & SAFETY GATEKEEPER                        │
│  - TCC Permission Verification Gate (Pre-flight check)                 │
│  - Risk Engine & Interactive Confirmation (HIGH / BLOCKED actions)     │
│  - Primary Dispatch: Native Swift AX / System APIs                     │
│  - Fallback Dispatch: Vision Grounding & Coordinate Clicks             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 CLOSED-LOOP STATE OBSERVATION & DELTA                  │
│  - Pre-Action Snapshot (State S0)                                      │
│  - Action Dispatch (Timestamp T9 recorded at syscall invocation)       │
│  - Post-Action Snapshot (State S1)                                     │
│  - Structural State Delta Computation (App, Window, Element, Hardware) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   TRUTHFUL VERIFICATION ENGINE                         │
│  - Evaluates Exact User Postcondition (Not Tool Return Success)        │
│  - Evaluates Target Value Equivalences (e.g. Brightness == 0.90)       │
│  - Strict Failure Isolation: Subsequent Success CANNOT Mask Failures   │
│  - Emits Truthful Statuses: SATISFIED | UNSATISFIED | UNKNOWN          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                STATE-DRIVEN REPLANNER & AUDIT LOG                      │
│  - Re-observation on Mismatch                                          │
│  - Re-grounding on Stale Targets                                       │
│  - Max Replan Bounds (Preserves original user goal)                    │
│  - Cryptographically Chained SHA-256 Audit Trail                       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 25. Phased Implementation Roadmap

1. **Phase 1: Verification Truthfulness & Anti-False-Success Hardening**  
   - *Dependencies:* None.  
   - *Scope:* Fix `GoalEvaluator.evaluate_goal` recovery loophole; eliminate silent step dropping in `Planner`; require strict independent postcondition verification.
2. **Phase 2: Audio Pipeline & Concurrency Repair**  
   - *Dependencies:* Phase 1.  
   - *Scope:* Eliminate dual-consumer stdout race condition in `audio_stream.py`; fix wake-word token boundary leak in `wake.py`.
3. **Phase 3: Semantic Parameter Extraction & Normalization**  
   - *Dependencies:* Phase 1.  
   - *Scope:* Replace brittle regexes in `normalization.py` and `intent.py` with structured slot extraction (preserve targets like "to 90%").
4. **Phase 4: World Model & Live macOS Introspection**  
   - *Dependencies:* Phase 1, Phase 3.  
   - *Scope:* Expand `EnvironmentObservation` to include display topology, audio status, hardware parameters, and cached TCC permissions.
5. **Phase 5: Dynamic Capability & App Intent Discovery**  
   - *Dependencies:* Phase 4.  
   - *Scope:* Implement dynamic discovery of macOS Shortcuts, CLI binaries, and application scripting dictionaries into `CapabilityRegistry`.
6. **Phase 6: Computer Use & Vision Hardening**  
   - *Dependencies:* Phase 4, Phase 5.  
   - *Scope:* Integrate Apple Vision Framework OCR into `VisionCapability` to ground VLM coordinates against physical text bounding boxes.
7. **Phase 7: Execution Safety & Permission Pre-Flight Gate**  
   - *Dependencies:* Phase 1, Phase 4.  
   - *Scope:* Enforce blocking TCC permission checks and risk confirmation directly inside `Executor.execute_step()`.
8. **Phase 8: Large-Scale Empirical Evaluation on Real macOS**  
   - *Dependencies:* Phases 1–7.  
   - *Scope:* Run non-mocked, live evaluation battery across third-party macOS applications with strict assertion of verified state.

---

## 26. File-Level Change Map

### EXISTING FILES TO EXTEND
- [`verification/evaluator.py`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py): Add explicit postcondition verifiers for target numerical values (e.g. brightness target levels).
- [`agent/observer.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/observer.py): Extend `EnvironmentObservation` with display geometry and hardware metrics.
- [`security/permissions.py`](file:///Users/aayushnmadeo/Documents/MAX/security/permissions.py): Add fast pre-flight permission query methods for `Executor`.
- [`capabilities/registry.py`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/registry.py): Add dynamic capability registration methods.

### EXISTING FILES TO REFACTOR
- [`verification/evaluator.py`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py): **Delete lines 686–691** (the false-success recovery loophole where later successes mask earlier failures).
- [`agent/planner.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/planner.py): **Delete lines 156–160** (the silent dropping of unregistered plan steps).
- [`voice/audio_stream.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/audio_stream.py): Remove direct `stdout.read()` in `capture_utterance()`; read strictly from the thread-safe ring buffer.
- [`voice/wake.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/wake.py): Fix regex boundary logic to prevent token leakage on non-prefix triggers.
- [`voice/normalization.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/normalization.py) & [`agent/intent.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/intent.py): Extract semantic numerical parameters rather than hardcoding deltas.
- [`agent/core.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py): Replace natural-language substring matching (`"not supported"`) with structured enums.

### NEW FILES LIKELY REQUIRED (Future Phases)
- `macos/display_topology.py`: Multi-monitor geometry and Retina scaling factor resolution via CoreGraphics / AppKit.
- `macos/shortcuts.py`: Discovery and invocation bridge for macOS Shortcuts (`shortcuts list / run`).
- `capabilities/vision/ocr.py`: Native OCR engine using Apple Vision Framework (`VNRecognizeTextRequest`).

### FILES THAT SHOULD NOT BE TOUCHED
- [`capabilities/accessibility/native_tree.swift`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/accessibility/native_tree.swift): Working, highly efficient native Swift AX inspector.
- [`capabilities/accessibility/native_backend.py`](file:///Users/aayushnmadeo/Documents/MAX/capabilities/accessibility/native_backend.py): Stable subprocess wrapper for `max-ax-tree`.
- [`voice/whisper_stt.py`](file:///Users/aayushnmadeo/Documents/MAX/voice/whisper_stt.py): Clean, verified local Whisper STT implementation.
- [`security/audit.py`](file:///Users/aayushnmadeo/Documents/MAX/security/audit.py): Solid cryptographic SHA-256 audit logger.
- [`tasks/manager.py`](file:///Users/aayushnmadeo/Documents/MAX/tasks/manager.py): Robust SQLite-backed background task manager.

---

## 27. Recommended Next Phase

### Recommended Phase: **PHASE 1 — VERIFICATION TRUTHFULNESS & ANTI-FALSE-SUCCESS HARDENING**

### Why It Must Come Next:
In an autonomous computer-use agent, **the truthfulness of the verifier is the foundation upon which all other capabilities depend**. If the verifier lies by returning `SATISFIED` when actions fail:
1. Replanning cannot function because failures are falsely treated as successes.
2. The planner cannot improve because feedback is corrupted.
3. Tests become meaningless because broken live runs report passing marks.
4. User safety is compromised because unexecuted or partially executed operations report successful completion.

Until MAX truthfully reports `FAILED` and `UNKNOWN` when postconditions are not proven, no progress can be trusted.

---

## WHAT I WOULD IMPLEMENT FIRST

### 1. The Single Highest-Priority Architectural Issue
The false-success vulnerability caused by the combination of:
- The recovery loophole in `GoalEvaluator.evaluate_goal()` ([`verification/evaluator.py:681-692`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py#L681-L692)), and
- The silent filtering of unregistered plan steps in `Planner.create_plan()` ([`agent/planner.py:156-160`](file:///Users/aayushnmadeo/Documents/MAX/agent/planner.py#L156-L160)).

### 2. Why It Must Be Addressed First
This defect is actively causing real-world failures to be reported as successes. In the observed production run, `accessibility.click_element` failed, yet the agent reported `SATISFIED` merely because the subsequent step reactivated the frontmost application. If this is not corrected first, every benchmark and validation suite will continue to yield false confidence.

### 3. The Exact Existing Files Involved
- [`verification/evaluator.py`](file:///Users/aayushnmadeo/Documents/MAX/verification/evaluator.py): Lines 681–744.
- [`agent/planner.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/planner.py): Lines 149–173.
- [`agent/core.py`](file:///Users/aayushnmadeo/Documents/MAX/agent/core.py): Lines 120–170 and 315–350.

### 4. What the Next Implementation Phase Should Accomplish
1. **Eliminate False-Recovery:** Refactor `GoalEvaluator.evaluate_goal()` so that every mandatory step in the original plan must have an independently verified status of `SATISFIED`. A subsequent action succeeding must NEVER mark an earlier required action's failure as "recovered" unless the replanner explicitly synthesized an alternative plan that satisfied the exact postcondition of the failed step.
2. **Strict Plan Gating:** Refactor `Planner.create_plan()` so that if any mandatory step in a plan requires an unregistered or unsupported capability, the entire plan is immediately rejected as `UNSUPPORTED`. It must never silently execute a partial plan.
3. **Target Postcondition Evaluation:** Ensure that when a user asks for an explicit state (e.g. brightness at 90%), the evaluator validates that the observed post-state matches that explicit parameter within a tight tolerance, rather than merely verifying that a directional change occurred.

### 5. What MUST NOT Be Changed During That Phase
- Do NOT modify `capabilities/accessibility/native_tree.swift` or recompile the binary.
- Do NOT rewrite the Whisper STT engine or TTS pipeline.
- Do NOT redesign the SQLite task manager or event bus.
- Do NOT add new dependencies to `pyproject.toml`.
- Do NOT attempt to build dynamic capability discovery before verification truthfulness is established.

### 6. How We Will Prove the Implementation is Real Rather Than Test-Gamed
We will prove correctness via empirical live testing against macOS:
1. **Live Negative Probe:** Intentionally execute an invalid click target in a real macOS application (e.g. TextEdit). Verify that `AgentCore` terminates with `status = UNSATISFIED` or `FAILED`, and that `GoalEvaluation` explicitly reports the failed step without masking it.
2. **Unsupported Mixed-Plan Probe:** Submit a compound request containing one registered action and one impossible action. Verify that the agent rejects the plan upfront with `status = UNSUPPORTED` and executes zero partial steps.
3. **Live Parameter Probe:** Execute `"increase my brightness to 90%"`. Verify that if the linear brightness does not reach $\ge 0.85$, the evaluator reports `UNSATISFIED` rather than `SATISFIED`.
4. **Zero-Mock Verification:** These probes must run against real macOS processes without `unittest.mock.patch` applied to `subprocess.run`, `DisplayServices`, or `GoalEvaluator`.
