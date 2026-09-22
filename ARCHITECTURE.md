# MAX System Architecture

## Overview
MAX is an autonomous computer-use agent designed for macOS. Rather than mapping user phrases to a fixed set of commands, MAX treats the Mac as a dynamic environment composed of general interfaces (terminal, filesystem, applications, system APIs).

```text
USER OUTCOME REQUEST
        ↓
OBSERVER (Inspect active app, cwd, running processes)
        ↓
CONTEXT ENGINE (Assemble live machine state, memories, preferences)
        ↓
PLANNER (Dynamic multi-step plan generation via LLM)
        ↓
FOR EACH STEP:
    RISK & POLICY CHECK (Assess command risk; prompt user if HIGH)
            ↓
    EXECUTOR (Run capability operation on real macOS)
            ↓
    OBSERVER (Inspect post-step state, capture real evidence)
            ↓
    EVALUATOR & REPLANNER (Verify step outcome; branch/adapt on failure)
        ↓
RESULT REPORTER (Factual report based strictly on real evidence)
```

---

## Subsystem Breakdown

### 1. Capability System (`capabilities/`)
All computer control operations are encapsulated in capabilities that register with `CapabilityRegistry`:
* `terminal`: General execution of shell commands, CLI utilities, and scripts via `/bin/zsh`. Captures stdout, stderr, and exit codes.
* `filesystem`: Targeted search (`find_files`), directory listing (`list_directory`), reading/writing, metadata inspection (`get_metadata`), and reversible deletion (`move_to_trash` via AppleScript).
* `applications`: Dynamic discovery across standard application directories (`/Applications`, `/System/Applications`, `~/Applications`), launch via `/usr/bin/open`, activation, process presence verification.
* `macos`: Native system interfaces including clipboard (`pbcopy`/`pbpaste`), Spotlight (`mdfind`), desktop notifications, and system settings (`defaults`).
* `developer`: Git repository inspection, project stack auto-detection, and local listening ports (`lsof`).

### 2. Observation Engine (`agent/observer.py`)
Observation is a first-class capability. MAX queries:
- Frontmost active application via AppleScript System Events
- Current working directory via `os.getcwd()`
- Running process sample via `ps -A`
- Clipboard preview via `pbpaste`

### 3. Security & Risk Engine (`security/`)
Actions are analyzed dynamically:
- **`BLOCKED`**: Destructive root actions (`rm -rf /`, `mkfs`, raw disk writes, piping unverified web scripts to shell).
- **`HIGH`**: Recursive file deletions, force pushes, privilege escalation (`sudo`). Triggers an interactive confirmation prompt (`y/N`).
- **`MEDIUM`**: Package installs, build commands, file modifications.
- **`SAFE` / `LOW`**: Read-only inspections, standard tool runs.
- **Audit Logger (`security/audit.py`)**: Tamper-evident JSONL logging of all requested tools, risk levels, arguments, and outcomes into `~/.max/audit.jsonl`.

### 4. Memory Subsystem (`memory/`)
SQLite-backed persistent storage in `~/.max/memory.db`:
- Explicit memories (`remember`, `forget`, `list`)
- User preferences (e.g. editor, default project paths)
- Session conversation history
