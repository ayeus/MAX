# ⚡ MAX — Autonomous Local macOS Computer Agent

<p align="center">
  <img src="https://img.shields.io/badge/Platform-macOS%2014%2B%20(Apple%20Silicon)-black?style=for-the-badge&logo=apple" alt="macOS" />
  <img src="https://img.shields.io/badge/Local%20LLM-Ollama-blueviolet?style=for-the-badge&logo=ollama" alt="Ollama" />
  <img src="https://img.shields.io/badge/Speech%20to%20Text-Local%20Whisper-00A67E?style=for-the-badge&logo=openai" alt="Whisper" />
  <img src="https://img.shields.io/badge/Python-3.12%2B%20%7C%203.13-blue?style=for-the-badge&logo=python" alt="Python" />
  <img src="https://img.shields.io/badge/Tests-118%20Passing-success?style=for-the-badge" alt="Tests Passing" />
  <img src="https://img.shields.io/badge/Privacy-100%25%20Local%20%26%20Offline-green?style=for-the-badge" alt="Local Privacy" />
</p>

<h3 align="center">
  A local-first, general-purpose autonomous computer operator for macOS.<br/>
  Control your Mac naturally by voice or text with closed-loop semantic verification.
</h3>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [Why MAX? (Architectural Differences)](#-why-max-architectural-differences)
- [System Architecture](#-system-architecture)
- [Core Engines & Innovations](#-core-engines--innovations)
  - [1. General-Purpose Computer Use Engine](#1-general-purpose-computer-use-engine)
  - [2. Deterministic-First Verification Subsystem](#2-deterministic-first-verification-subsystem)
  - [3. Continuous Hands-Free Voice Assistant](#3-continuous-hands-free-voice-assistant)
  - [4. Process Supervision & Event Engine](#4-process-supervision--event-engine)
  - [5. Security, Risk Analysis & Audit Trails](#5-security-risk-analysis--audit-trails)
- [Installation & Setup](#-installation--setup)
- [CLI Reference & Usage Guide](#-cli-reference--usage-guide)
  - [Hands-Free Voice Mode (`max listen`)](#1-hands-free-voice-mode-max-listen)
  - [Natural Language Task Execution (`max text`)](#2-natural-language-task-execution-max-text)
  - [Push-to-Talk Voice (`max voice`)](#3-push-to-talk-voice-max-voice)
  - [System Diagnostics (`max doctor`)](#4-system-diagnostics-max-doctor)
  - [Background Task Supervision (`max task`)](#5-background-task-supervision-max-task)
  - [Memory & Preference Engine (`max memory`)](#6-memory--preference-engine-max-memory)
  - [Workflow Automation (`max workflow`)](#7-workflow-automation-max-workflow)
- [Automated Testing & Verification](#-automated-testing--verification)
- [Privacy & Security Guarantee](#-privacy--security-guarantee)
- [License](#-license)

---

## 🌟 Overview

**MAX** is not a voice assistant that matches keywords against a hardcoded menu of canned actions.

MAX is a **general-purpose computer operator** that perceives your Mac's live desktop state, reasons over user intent, inspects semantic accessibility trees, executes multi-step plans across applications and terminals, and deterministically verifies the real operating system outcome before reporting success.

```text
"Open Notes, create a new note titled 'Project Roadmap', and draft the Q4 milestones."
"Find all uncommitted Python files in this repo, run their unit tests, and show me failures."
"Open Chrome, navigate to the local dashboard on port 3000, and copy the auth token."
```

MAX executes these multi-step workflows **completely locally** on Apple Silicon using local Ollama models (`qwen2.5-7b-instruct`, `llama-3.1-8b`), local OpenAI Whisper STT, native macOS Accessibility APIs, and native system synthesis. **Zero telemetry. Zero external API keys. Zero cloud latency.**

---

## ⚖️ Why MAX? (Architectural Differences)

| Capability | Siri / Typical Assistants | Cloud Agent APIs (Anthropic/OpenAI) | **MAX 2.0 Local Agent** |
| :--- | :--- | :--- | :--- |
| **Execution Domain** | Canned app shortcuts & search | Remote screenshots / VMs | **Native macOS host (System APIs, Terminal, GUI)** |
| **Model Hosting** | Cloud servers | Cloud servers | **100% Local (Ollama on Apple Silicon M-Series)** |
| **GUI Targeting** | None (Limited Apple Events) | Raw pixel coordinates $(x, y)$ | **Semantic Accessibility Trees (`AXRoles`, titles, labels)** |
| **Disambiguation** | Fails or asks user | Clicks blindly on ambiguous coordinates | **Mathematical multi-signal scoring with ambiguity rejection** |
| **Verification** | Assumes success if intent parsed | VLM visual comparison (prone to hallucinations) | **Deterministic OS verification (processes, filesystem, AX state)** |
| **Multi-Step App Tasks** | Launch application and stop | Screenshot loop with high cost/latency | **Autonomous closed-loop continuation loop** |
| **Privacy & Security** | Audio & telemetry streamed to cloud | Screen captures streamed to cloud | **Strictly offline; tamper-evident local JSONL audit trail** |
| **Background Tasks** | Cannot supervise background processes | Cannot access local process trees | **Process group isolation (`killpg`), watchers, and EventBus** |

---

## 🏗️ System Architecture

MAX operates as a continuous, closed-loop state machine:

```text
                           ┌────────────────────────────┐
                           │     User Spoken / Text     │
                           │       Outcome Request      │
                           └─────────────┬──────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          PERCEPTION & STATE OBSERVATION                         │
│  • lsappinfo fast PID query   • AccessibilityTreeExtractor (AX hierarchy)       │
│  • Bounded window controls     • Terminal cwd, processes sample & pbpaste       │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               REASONING & PLANNING                              │
│  • Context Assembler (State + Preferences + Memories + Task History)            │
│  • Local Ollama LLM (Decomposes outcomes into structured capability operations) │
│  • Resilient Cross-Capability Router                                            │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                             SAFETY & RISK ENGINE                                │
│  • Dynamic Risk Classifier (SAFE, LOW, MEDIUM, HIGH, CRITICAL, BLOCKED)         │
│  • High-risk interactive confirmation (y/N)  • Tamper-evident audit.jsonl       │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          ACTION DISPATCH & EXECUTION                            │
│  • SemanticUIGrounder (multi-signal role/title/description matching)           │
│  • System Events & Accessibility Action Dispatch (AXPress, AXConfirm)          │
│  • Native CoreGraphics mouse & scroll driver (ctypes fallback)                  │
│  • Subprocess Session Supervision (`start_new_session=True`, `os.killpg`)       │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     DETERMINISTIC VERIFICATION & RECOVERY                       │
│  • Deterministic OS verification (Process list, filesystem state, AX values)   │
│  • Type ≠ Send Enforcement (drafting text never automatically submits)         │
│  • Replanner & Self-Healing (diagnoses issues and generates recovery actions)   │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                     ┌───────────────────┴───────────────────┐
                     │ Goal Satisfied?                       │
                    YES                                      NO
                     ▼                                       ▼
       ┌───────────────────────────┐          ┌─────────────────────────────┐
       │ Factual Evidence Summary  │          │ Re-Observe UI & Trigger     │
       │ & Native macOS Speech TTS │          │ Multi-Step Continuation     │
       └───────────────────────────┘          └─────────────────────────────┘
```

---

## 🔬 Core Engines & Innovations

### 1. General-Purpose Computer Use Engine

Unlike fragile agents that rely on screen scraping or hardcoded coordinates, MAX interacts with applications semantically:

- **Bounded Tree Extraction (`capabilities/accessibility/tree.py`)**: Traverses the active macOS application's Accessibility hierarchy (`AXButton`, `AXTextField`, `AXTextArea`, `AXSearchField`, `AXPopUpButton`, `AXCheckBox`, `AXScrollArea`) in under **0.3 seconds** without hanging Electron or complex web apps.
- **Semantic UI Grounder (`capabilities/accessibility/grounding.py`)**: Uses multi-signal scoring based on:
  - Accessible role and role alias expansion (`button`, `text_field`, `input`, `search`, `tab`, `checkbox`).
  - Exact and substring label matching.
  - Accessibility description and placeholder resolution.
  - Token overlap ratios.
  - Current value and automation identifier matching.
- **Ambiguity Rejection**: If multiple interactive candidates share identical scores (e.g. two conflicting "Save" buttons) without unambiguous context, MAX **refuses blind execution** (`is_reliable = False`, confidence `WEAK`) rather than clicking destructive targets.
- **Native CoreGraphics Pointer Dispatch (`capabilities/accessibility/mouse.py`)**: Zero-dependency C-types bridge directly into `/System/Library/Frameworks/CoreGraphics.framework` for precise clicks, double-clicks, and smooth scroll wheel events.
- **Multi-Step Closed-Loop Continuation (`agent/core.py`)**: Eliminates the premature stop defect. If a 1-step launch occurs but the overall goal requires further interaction (e.g. typing or messaging), `AgentCore` dynamically re-observes the newly active window and plans subsequent interaction steps until the goal is fully achieved.

---

### 2. Deterministic-First Verification Subsystem

MAX enforces a non-negotiable rule: **Zero Fake Verification.**

- **Deterministic Hierarchy**:
  1. **Process State**: Direct kernel PID validation (`os.kill(pid, 0)`), process naming (`ps -A`), and bundle verification.
  2. **Filesystem State**: Path existence, byte size checks, and checksum validation.
  3. **Accessibility State**: Real UI element focus states, text entry values, and window titles.
  4. **Terminal State**: Process return codes, stdout, and stderr streams.
  5. **Vision Fallback**: Screen-difference or VLM verification is invoked **strictly** when deterministic OS queries are fundamentally impossible.
- **Unverified = UNKNOWN**: An action that completes without verifiable OS evidence reports `UNKNOWN`, never fake `SUCCESS`.
- **Type $\neq$ Send Rule**: Typing into an application or drafting text does **not** equal sending. Return is pressed or Send is clicked only when the user explicitly commanded submission.
- **Interaction Completeness**: If the user's intent requested interaction (*"Open WhatsApp and message John..."*), merely launching the application evaluates to `UNSATISFIED`.

---

### 3. Continuous Hands-Free Voice Assistant

MAX operates as a native voice assistant running continuously in the background:

- **Swift Audio Streaming (`bin/max-audio-stream` / `voice/audio_stream.swift`)**: High-performance streaming audio capture via macOS `AVFoundation` with minimal CPU and memory overhead.
- **Instant Wake Word Detection (`voice/wake.py`)**: Ultra-low-latency detection of *"Max"* or *"Hey Max"*.
- **Earcon Audio Feedback**: Plays a native macOS system acknowledgement chime (`/System/Library/Sounds/Tink.aiff`) immediately upon wake word detection so you know MAX is listening without looking at your screen.
- **Local Whisper STT (`voice/whisper_stt.py`)**: Transcribes speech using local OpenAI Whisper (`base.en` or `small.en`) running on Apple Silicon Neural Engine / Metal.
- **Spoken Cancellation**: Say *"Max, stop"*, *"cancel"*, or *"abort"* at any point during planning or execution to halt the agent immediately.
- **Voice Watchdog**: Background monitor prevents thread hangs or orphaned states, automatically resetting to `IDLE` if an action exceeds execution timeouts.

---

### 4. Process Supervision & Event Engine

MAX provides enterprise-grade process lifecycle management:

- **Process Isolation**: Every background job is launched in an isolated process group via `subprocess.Popen(..., start_new_session=True)`.
- **Process Tree Termination**: Terminating a task targets the entire process group using `os.killpg(pgid, signal.SIGTERM)`, escalating to `SIGKILL` after a grace period. Child processes (e.g. Node spawned by npm) are never orphaned.
- **SQLite Persistence & Startup Reconciliation**: All task metadata is persisted in `~/.max/memory.db`. On startup, MAX inspects OS processes to reconcile dead or orphaned jobs.
- **Filesystem & Port Watchers**:
  - `DirectoryWatcher`: Debounced polling observer tracking file additions, updates, and deletions.
  - `PortWatcher`: TCP socket listener detecting when local services (e.g. Vite, Next.js, FastAPI) begin listening on a port.
- **Thread-Safe EventBus**: Thread-pool dispatch with deterministic condition synchronization (`EventBus.wait_for()`), allowing MAX to await long-running builds without wasting LLM tokens on polling loops.

---

### 5. Security, Risk Analysis & Audit Trails

Security is built into the runtime, not bolted on:

- **5-Tier Risk Classification (`security/risk.py`)**:
  - `BLOCKED`: Catastrophic actions (`rm -rf /`, raw disk formatting, piping remote scripts to bash) are hard-blocked unconditionally.
  - `CRITICAL` / `HIGH`: Mass file modifications, privilege escalation (`sudo`), git force-pushes require interactive terminal confirmation (`y/N`).
  - `MEDIUM`: Software installation, background daemons, GUI keystrokes.
  - `LOW` / `SAFE`: Read-only inspections, system defaults queries, active window checks.
- **Audit Logging (`security/audit.py`)**: Every tool request, parameter, risk level, and execution result is recorded to `~/.max/audit.jsonl` with timestamps and cryptographic UUIDs.

---

## 🚀 Installation & Setup

### Prerequisites

- **macOS Sonoma (14.0+)** or **macOS Sequoia (15.0+)** (Apple Silicon recommended: M1, M2, M3, M4).
- **Python 3.12+** or **3.13**.
- **Ollama** installed and running locally:
  ```bash
  brew install ollama
  ollama serve
  ```
- Pull recommended local reasoning models:
  ```bash
  ollama pull qwen2.5-7b-instruct:latest
  ollama pull moondream:latest
  ```

### Step 1: Clone and Install

```bash
git clone https://github.com/ayeus/MAX.git
cd MAX

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install MAX in editable mode
pip install -e .
```

### Step 2: Configure macOS Permissions

MAX requires standard macOS Privacy & Security permissions to control applications and inspect UI elements:
1. **Accessibility**: `System Settings > Privacy & Security > Accessibility` (Grant your terminal emulator / IDE).
2. **Screen Recording**: `System Settings > Privacy & Security > Screen Recording` (Required for vision fallback).
3. **Microphone**: Granted on first audio prompt for voice commands.

### Step 3: Run System Diagnostics

Verify your local toolchains, Ollama connection, and permissions:
```bash
max doctor
```

```text
┌──────────────────────────┬───────────────────────────────────────────────────┐
│ Property                 │ Status / Value                                    │
├──────────────────────────┼───────────────────────────────────────────────────┤
│ Operating System         │ macOS 15.6 (arm64)                                │
│ Python Runtime           │ Python 3.13.5 (/usr/local/bin/python3)             │
│ Ollama Service           │ http://localhost:11434 (Online & Responding)      │
│ Configured Reasoning     │ qwen2.5-7b-instruct:latest                        │
│ Accessibility Permission │ ✓ GRANTED                                         │
│ Screen Recording         │ ✓ GRANTED                                         │
│ Task Store (SQLite)      │ ~/.max/memory.db (Online)                         │
└──────────────────────────┴───────────────────────────────────────────────────┘
```

---

## 💻 CLI Reference & Usage Guide

```text
Usage: max [OPTIONS] COMMAND [ARGS]...

  MAX — Local General-Purpose AI Computer Agent for macOS

Commands:
  listen    Continuous hands-free voice assistant mode. Call 'Max' to activate.
  text      Execute an arbitrary computer outcome request using natural language.
  voice     Push-to-talk interactive voice interface.
  doctor    Run exhaustive system environment, permission, and toolchain checks.
  task      Manage long-running background tasks, watchers, and daemons.
  memory    View and manage persistent memories and user preferences.
  workflow  View and replay saved workflow procedures.
  speak     Speak text out loud using native macOS speech synthesis.
  voices    List all available speech synthesis voices installed in macOS.
```

---

### 1. Hands-Free Voice Mode (`max listen`)

Start the continuous, hands-free assistant loop:

```bash
max listen
```

- **Options**:
  - `--wake-word, -w`: Wake word (default: `"max"`).
  - `--model, -m`: Whisper STT model (default: `"base.en"`).
  - `--voice, -v`: TTS voice name (e.g. `"Samantha"`, `"Daniel"`).

#### Voice Interaction Examples:
- **Two-stage interaction**:
  - You: *"Max"*
  - MAX: *(Plays Tink chime)* *"Yes, I'm listening."*
  - You: *"Check if Docker is running and launch it if not."*
  - MAX: *(Executes task and reports outcome)* *"Docker was not running; launched Docker successfully."*
- **One-shot direct interaction**:
  - You: *"Max, open TextEdit and type Project Roadmap Q4"*
  - MAX: *(Immediately begins execution, types text into editor, and confirms)*

---

### 2. Natural Language Task Execution (`max text`)

Execute arbitrary computer tasks directly from your shell:

```bash
# General OS & Filesystem Tasks
max text "Inspect my current directory and list all markdown and toml files"
max text "Find all screenshot images on my Desktop and organize them into a Screenshots folder"

# Developer & Git Workflows
max text "Check git status, show modified files, and tell me if there are uncommitted changes"
max text "Inspect the ports currently listening on my machine"

# Multi-Step GUI Application Tasks
max text "Open Notes, create a new note, and type meeting notes for today"
max text "Open TextEdit, type 'MAX 2.0 Autonomous Verification', and verify the window"

# Web Navigation
max text "Search Google Chrome for the latest Python 3.13 release notes"
```

Use `--debug` or `-d` to inspect internal step planning, timing, and evidence:
```bash
max text --debug "Inspect all processes consuming more than 10% CPU"
```

---

### 3. Push-to-Talk Voice (`max voice`)

Record a single spoken prompt with automatic Voice Activity Detection (VAD):

```bash
# Records audio, transcribes with local Whisper, executes outcome, and speaks response
max voice

# Run without spoken TTS response
max voice --no-speak
```

---

### 4. System Diagnostics (`max doctor`)

Inspect system health, local models, permissions, toolchains, and background tasks:

```bash
max doctor
```

---

### 5. Background Task Supervision (`max task`)

Supervise and control long-running jobs, dev servers, watchers, and processes:

```bash
# List all active and past background tasks
max task list

# Inspect detailed status, PID, PGID, and runtime
max task status <task_id>

# View streaming stdout/stderr log output
max task logs <task_id> --lines 100

# Terminate task and entire process group cleanly
max task kill <task_id>
```

---

### 6. Memory & Preference Engine (`max memory`)

Teach MAX personal preferences and long-term memories stored in `~/.max/memory.db`:

```bash
# Teach a preference
max memory remember --key editor --value "VS Code"
max memory remember --key project_dir --value "~/Documents/Code"

# List all stored memories and preferences
max memory list

# Forget a specific memory
max memory forget --key editor

# Clear all memories
max memory clear
```

---

### 7. Workflow Automation (`max workflow`)

Save and replay multi-step procedures deterministically:

```bash
# List all saved workflows
max workflow list

# Execute a saved workflow by name
max workflow run --name daily_standup

# Inspect workflow steps
max workflow show --name daily_standup
```

---

## 🧪 Automated Testing & Verification

MAX is tested with strict assertions: zero mocked success in production paths, zero hardcoded strings, and full coverage across capabilities, task supervision, voice detection, and goal verification.

### Run All 118 Tests

```bash
python3 -m unittest discover -s tests -v
```

```text
Ran 118 tests in 60.796s

OK
```

### Test Suite Breakdown:

- `test_computer_use_grounding.py`: Multi-signal element resolution, role aliases, and ambiguity rejection.
- `test_computer_use_accessibility.py`: Accessibility tree extraction, semantic clicking, typing, and deterministic verification.
- `test_computer_use_agent.py`: AgentCore closed-loop multi-step continuation and intent completeness checks.
- `test_goal_verification.py`: Deterministic OS verification (process presence, filesystem state, unverified actions).
- `test_tasks.py`: Real background process isolation, process group termination, and `EventBus` deterministic waiting.
- `test_wake_word.py`: Standalone wake word, inline command extraction, and negative false-positive rejection.
- `test_voice_reliability.py`: Voice watchdog auto-recovery, spoken cancellation, and earcon audio fallbacks.
- `test_security_hardening.py`: Hard-blocked catastrophic commands and high-risk confirmation guards.
- `test_soak.py`: 5-command mini soak suite verifying zero memory leaks or dropped execution cycles.

---

## 🛡️ Privacy & Security Guarantee

1. **100% Local Inference**: All reasoning, planning, speech-to-text, and text-to-speech are executed on your device using Ollama, local Whisper, and macOS native speech engines.
2. **Zero Telemetry**: MAX makes no outbound phone-home calls, analytics requests, or telemetry tracking.
3. **No Blind Clicks**: MAX grounds UI controls through Accessibility labels and rejects ambiguous targets rather than guessing coordinates.
4. **Reversible File Operations**: Deletions requested through the filesystem capability are sent to macOS Trash (`~/.Trash`) via AppleScript, rather than permanently deleted.
5. **Auditable**: Every single tool call, command argument, and status change is logged locally to `~/.max/audit.jsonl`.

---

## 📄 License

This project is licensed under the **MIT License**. Feel free to use, modify, and distribute for personal and commercial applications.
