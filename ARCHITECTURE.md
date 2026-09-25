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

### 1. Dynamic Capability Platform (`capabilities/`)
MAX utilizes a decentralized, multi-provider capability architecture (documented in [ADR-002](docs/architecture/ADR-002-dynamic-capability-platform.md)) that completely separates capability discovery from execution:

- **Canonical Metadata Descriptors (`capabilities/models.py`)**:
  - **Hierarchical Identity**: Decouples the parent capability identity (`capability_id`, e.g., `filesystem.file`) from individual operations (`operation_id`, e.g., `write`, fully-qualified `filesystem.file.write`).
  - **Availability Lifecycle (`AvailabilityStatus`)**: Explicit states (`AVAILABLE`, `DISABLED`, `MISSING_DEPENDENCY`, `PERMISSION_BLOCKED`, `DEGRADED`, `UNKNOWN`) with structured `AvailabilityInfo` providing remediation guidance.
  - **Permission Model (`RequiredPermission`)**: Identifies macOS TCC and system settings requirements with direct navigation URL anchors.
  - **Generic Constraints (`CapabilityConstraint`)**: Polymorphic, composable operational constraints including `RateLimitConstraint`, `TimeoutConstraint`, `ExecutionModeConstraint`, `ConcurrencyConstraint`, `PlatformConstraint`, and `CustomConstraint`.
  - **Risk & Blast Radius (`CapabilityRisk`)**: Granular risk levels, confirmation requirements, reversibility flags, and blast radius declarations.
  - **Verification Contracts (`VerificationContract`)**: Declares supported deterministic verification methods and postcondition requirements.
  - **Provenance Tracking (`CapabilityProvenance`)**: Explicit source tracking (`BUILTIN`, `SYSTEM_APP_INTENTS`, `SYSTEM_SHORTCUTS`, `ACCESSIBILITY_DISCOVERED`, `PLUGIN`, `CUSTOM`), provider IDs, semantic versioning, and priority rankings.

- **Decoupled Provider Interfaces (`capabilities/provider.py`)**:
  - `CapabilityDiscoveryProvider`: Discovers capabilities and queries availability states without triggering execution side-effects.
  - `CapabilityExecutionProvider`: Executes operations against strongly-typed parameter schemas.
  - `CapabilityProvider`: Composite protocol combining both discovery and execution.
  - `LegacyCapabilityAdapter`: Backward-compatibility adapter that exposes legacy `BaseCapability` instances as canonical descriptors and execution providers with zero breaking changes.

- **Multi-Provider Registry & Targeted Cache (`capabilities/registry.py`, `capabilities/cache.py`)**:
  - Registers multiple heterogeneous discovery and execution providers simultaneously.
  - Supports filtered queries across availability status, risk tier, source type, and provider IDs.
  - `InMemoryCapabilityCache`: Thread-safe cache with targeted invalidation along three distinct axes:
    1. By Capability ID
    2. By Provider ID
    3. By Provenance Source Type

- **Standard Built-in Execution Capabilities**:
  * `terminal`: General execution of shell commands, CLI utilities, and scripts via `/bin/zsh`. Captures stdout, stderr, and exit codes.
  * `filesystem`: Targeted search (`find_files`), directory listing (`list_directory`), reading/writing, metadata inspection (`get_metadata`), and reversible deletion (`move_to_trash` via AppleScript).
  * `applications`: Dynamic discovery across standard application directories (`/Applications`, `/System/Applications`, `~/Applications`), launch via `/usr/bin/open`, activation, process presence verification.
  * `macos`: Native system interfaces including clipboard (`pbcopy`/`pbpaste`), Spotlight (`mdfind`), desktop notifications, system settings (`defaults`), and native display brightness via CoreDisplay/DisplayServices with SDR/HDR linear fallbacks.
  * `developer`: Git repository inspection, project stack auto-detection, and local listening ports (`lsof`).
  * `accessibility`: Semantic UI grounding and interaction via Accessibility APIs (`AXUIElementCopyAttributeValue`, `AXUIElementPerformAction`) and native CoreGraphics pointer dispatch.
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
- **Audit Logger (`security/audit.py`)**: Tamper-evident JSONL logging of all requested tools, risk levels, arguments, and outcomes into `~/.max/audit.jsonl` with cryptographic hash chaining.

### 4. Memory Subsystem (`memory/`)
SQLite-backed persistent storage in `~/.max/memory.db`:
- Explicit memories (`remember`, `forget`, `list`)
- User preferences (e.g. editor, default project paths)
- Session conversation history

### 5. Long-Running Task & Process Supervisor (`tasks/`)
Real background task execution and lifecycle supervision:
- **Process Isolation**: Every background job is launched in an independent process group via `subprocess.Popen(..., start_new_session=True)`.
- **Tree Termination**: When a task is cancelled, `TaskManager` signals the entire process group using `os.killpg(pgid, signal.SIGTERM)`, falling back to `SIGKILL` after a grace period. This guarantees child processes (e.g. node spawned by npm) are never orphaned.
- **Process Identity & PID Reuse Protection**: Captures creation timestamps via `libproc` / `proc_pidinfo` and verifies identity before issuing signals to prevent misdirected terminations if a PID is recycled by the OS kernel.
- **Bounded Stream Logging**: Task stdout and stderr are continuously written to `~/.max/logs/tasks/{task_id}.log`. Log retrieval tools read the trailing lines without loading unbounded files into memory.
- **SQLite Persistence & Startup Orphan Reconciliation**: Tasks are persisted in the `managed_tasks` SQLite table. On system startup, `reconcile_orphan_tasks()` queries active OS processes (`os.kill(pid, 0)` and `ps`) to verify survival and mark dead/vanished processes appropriately.

### 6. Event Engine & Deterministic Waiting (`event_engine/`)
Event-driven reactive coordination:
- **Thread-Safe EventBus**: Subscriptions, thread-pool dispatch, bounded event history (last 500 events).
- **Typed Lifecycle Events**: `ProcessStartedEvent`, `ProcessExitedEvent`, `TaskCompletedEvent`, `TaskFailedEvent`, `TaskCancelledEvent`, `FileCreatedEvent`, `FileModifiedEvent`, `FileDeletedEvent`, `ServiceStatusChangedEvent`.
- **Zero LLM Waste During Wait**: When MAX needs to await a long-running build, test suite, or file modification, it halts LLM invocation and uses deterministic condition synchronization (`EventBus.wait_for()`), only awakening the agent once the event fires or times out.

### 7. Truthful Execution & Anti-False-Success Verification Subsystem (`agent/verifier.py`, `agent/core.py`)
MAX enforces strict semantic verification guarantees to eliminate false successes:
- **Core Invariant**:
  ```text
  EXECUTION SUCCESS != GOAL SUCCESS

  POSTCONDITION OBSERVED     → SATISFIED
  POSTCONDITION NOT PROVEN   → UNKNOWN
  POSTCONDITION PROVEN FALSE → UNSATISFIED
  ```
- **Explicit Postconditions**: Execution plans generated by the planner must declare expected postconditions. Success is never reported without verifiable evidence.
- **Deterministic Hierarchy**: Prefers OS process validation, filesystem state checks, and Accessibility attribute inspections over probabilistic vision models.
- **`Type != Send` Rule**: Typing into an application or drafting text never implies transmission. Explicit submission steps are required to claim a message or email was sent.
- **Interaction Completeness**: If the user's goal requested interaction (e.g. *"Open WhatsApp and message John"*), merely launching the application is evaluated as `UNSATISFIED`.

### 8. Voice Pipeline & Speech Normalization (`voice/`, `bin/max-audio-stream`)
Continuous hands-free voice assistance running fully on-device:
- **Swift Audio Streamer (`voice/audio_stream.swift`)**: High-efficiency circular audio buffer built with macOS `AVFoundation` for low-latency wake word detection.
- **Speech Normalization (`voice/normalization.py`)**: Repairs phonetic splits from Whisper (e.g., *"text edit"* → *"TextEdit"*), strips conversational filler prefixes, and normalizes spoken phrasing before planning.
- **System Sound Feedback (Earcons)**: Emits immediate audio feedback using native macOS system sounds (`Tink.aiff`) upon wake word recognition.
- **Voice Watchdog**: Independent monitor thread that recovers stuck or orphaned execution states back to `IDLE` after timeout thresholds.

