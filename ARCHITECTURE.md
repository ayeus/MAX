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
* `vision`: Local screen capture (`screencapture`), VLM understanding via Ollama (`moondream`), coordinate translation, and closed-loop visual clicks.
* `tasks`: Management of asynchronous background processes, daemons, filesystem observers, and TCP port monitors.

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

### 5. Long-Running Task & Process Supervisor (`tasks/`)
Real background task execution and lifecycle supervision:
- **Process Isolation**: Every background job is launched in an independent process group via `subprocess.Popen(..., start_new_session=True)`.
- **Tree Termination**: When a task is cancelled, `TaskManager` signals the entire process group using `os.killpg(pgid, signal.SIGTERM)`, falling back to `SIGKILL` after a grace period. This guarantees child processes (e.g. node spawned by npm) are never orphaned.
- **Bounded Stream Logging**: Task stdout and stderr are continuously written to `~/.max/logs/tasks/{task_id}.log`. Log retrieval tools read the trailing lines without loading unbounded files into memory.
- **SQLite Persistence & Startup Orphan Reconciliation**: Tasks are persisted in the `managed_tasks` SQLite table. On system startup, `reconcile_orphan_tasks()` queries active OS processes (`os.kill(pid, 0)` and `ps`) to verify survival and mark dead/vanished processes appropriately.

### 6. Event Engine & Deterministic Waiting (`event_engine/`)
Event-driven reactive coordination:
- **Thread-Safe EventBus**: Subscriptions, thread-pool dispatch, bounded event history (last 500 events).
- **Typed Lifecycle Events**: `ProcessStartedEvent`, `ProcessExitedEvent`, `TaskCompletedEvent`, `TaskFailedEvent`, `TaskCancelledEvent`, `FileCreatedEvent`, `FileModifiedEvent`, `FileDeletedEvent`, `ServiceStatusChangedEvent`.
- **Zero LLM Waste During Wait**: When MAX needs to await a long-running build, test suite, or file modification, it halts LLM invocation and uses deterministic condition synchronization (`EventBus.wait_for()`), only awakening the agent once the event fires or times out.

