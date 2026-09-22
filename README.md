# MAX — General-Purpose Local AI Computer Agent for macOS

MAX is a local-first, general-purpose autonomous computer operator for macOS.

MAX is **NOT** a limited voice assistant with a hardcoded command catalogue. It is an autonomous operator designed to understand arbitrary natural-language requests, inspect the user's Mac, select available capabilities, execute actions safely, observe real outputs, verify state changes, adapt to failures, and report factual results based strictly on real evidence.

---

## Key Highlights

- **Outcome-Oriented, Not Command-Oriented**: Speak naturally and describe what you want done (e.g. *"Inspect my Downloads and tell me what was added today"*, *"Find all Python files in my project"*).
- **Zero Mocking / 100% Real Execution**: Every tool queries the real macOS machine, runs actual commands via `/bin/zsh`, manages actual applications via `open`/AppleScript, and inspects real processes and files.
- **Closed-Loop Computer Control**: `OBSERVE → PLAN → EXECUTE → OBSERVE → VERIFY → ADAPT → REPORT`.
- **Dynamic Capability-Based Architecture**:
  - `terminal`: Arbitrary shell command generation, risk evaluation, timeout, stdout/stderr capture.
  - `filesystem`: Targeted search, reading, writing, metadata inspection, and reversible deletion (`move_to_trash`).
  - `applications`: Dynamic discovery across `/Applications`, launch, activation, process tracking.
  - `macos`: System clipboard (`pbcopy`/`pbpaste`), Spotlight (`mdfind`), desktop notifications, system settings (`defaults`).
  - `developer`: Git status, project stack detection (Node, Python, Go, Rust, Java, Docker), and listening ports (`lsof`).
- **Deep Security Subsystem**:
  - Dynamic risk classification (`SAFE`, `LOW`, `MEDIUM`, `HIGH`, `BLOCKED`).
  - Catastrophic operations (e.g. wiping `/` or `~`) are blocked unconditionally.
  - High-risk operations (e.g. recursive deletions, force pushes) require explicit terminal confirmation (`y/N`).
  - Tamper-evident JSONL audit logging in `~/.max/audit.jsonl`.
- **Local Model Architecture**: Runs against local Ollama (`http://localhost:11434`), defaulting to fast local models (`qwen2.5-7b-instruct:latest`, `llama-3.1-8b-instruct:latest`, etc.) with sub-second inference on Apple Silicon.

---

## Quickstart

### 1. Environment Diagnostics
Verify your Mac hardware, Ollama connectivity, models, and permissions:
```bash
./bin/max doctor
```

### 2. Natural Language Computer Outcomes
Execute arbitrary computer tasks:
```bash
# Filesystem outcome
./bin/max text "Inspect my current directory and list all markdown and toml files"

# Application control
./bin/max text "Check if Docker is running, and launch it if not"

# Terminal & Developer outcome
./bin/max text "Inspect git status of this repository and summarize recent changes"
```

### 3. Developer Mode (Execution Tracing)
Inspect step-by-step strategy, capability arguments, execution duration, and post-observations:
```bash
./bin/max debug "Find all python files modified in the last 7 days"
```

### 4. Memory & Preferences
Manage explicit user memories and preferences stored in SQLite (`~/.max/memory.db`):
```bash
./bin/max memory remember --key editor --value "VS Code"
./bin/max memory list
```

---

## Running Automated Tests

Run the complete test suite:
```bash
python3 -m unittest discover -s tests -v
```
