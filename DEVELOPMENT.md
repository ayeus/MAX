# MAX Development Guide

## Environment Prerequisites
- macOS on Apple Silicon (`arm64`) or Intel (`x86_64`)
- Python 3.11+
- Local Ollama instance running at `http://localhost:11434` with at least one instruct model (`qwen2.5-7b-instruct:latest`, `llama-3.1-8b-instruct:latest`, or similar)

---

## Project Structure
```text
MAX/
├── bin/
│   └── max                     # Executable CLI wrapper
├── app/
│   ├── main.py                 # CLI entrypoint (Typer/Click: text, debug, doctor, memory)
│   ├── config.py               # Dynamic settings and path resolution
│   └── diagnostics.py          # Real environment, hardware, and permissions inspection
├── agent/
│   ├── core.py                 # Closed-loop agent orchestration
│   ├── planner.py              # LLM outcome-to-plan translation
│   ├── executor.py             # Capability dispatcher
│   ├── observer.py             # Live system state observer
│   ├── context.py              # Live context assembler
│   └── replanner.py            # Failure diagnosis and adaptive recovery
├── llm/
│   ├── base.py                 # Abstract LLMProvider interface
│   ├── ollama.py               # Local Ollama REST client
│   ├── model_manager.py        # Model resolution and fallback
│   └── prompts/                # System, planning, and evaluation prompt constructors
├── capabilities/
│   ├── base.py                 # Capability and Operation base models
│   ├── registry.py             # Central registry
│   ├── terminal/               # General shell execution
│   ├── filesystem/             # Search, read, write, trash, metadata
│   ├── applications/           # Discovery, launch, activation, process tracking
│   ├── macos/                  # Clipboard, notifications, spotlight, defaults
│   ├── developer/              # Git status, project stacks, listening ports
│   ├── vision/                 # Vision fallback & screen targets
│   └── tasks/                  # Background tasks, processes, and event monitors
├── tasks/
│   ├── models.py               # TaskState, TaskType, ManagedTask
│   ├── persistence.py          # SQLite persistence & orphan recovery
│   ├── supervisor.py           # Process group launcher & log streamer
│   ├── watchers.py             # DirectoryWatcher & PortWatcher
│   └── manager.py              # Central TaskManager singleton
├── event_engine/
│   ├── events.py               # Typed event schemas
│   └── bus.py                  # Thread-safe EventBus & wait_for
├── vision/                     # Local screen capture, VLM analysis & click execution
├── security/
│   ├── risk.py                 # Dynamic risk classification engine
│   ├── policy.py               # Policy enforcement
│   ├── confirmation.py         # Binary terminal confirmation (y/N)
│   ├── permissions.py          # macOS TCC permissions inspector
│   └── audit.py                # JSONL audit logger
├── memory/
│   ├── database.py             # SQLite persistence engine
│   ├── memories.py             # Explicit user memories
│   └── preferences.py          # Key-value user preferences
├── macos/
│   ├── shell.py                # Subprocess runner with timeout
│   └── applescript.py          # AppleScript runner with error code translation
└── tests/                      # Automated test suite (50+ unit and live tests)
```

---

## Adding a New Capability

1. Subclass `capabilities.base.Capability`.
2. Define operations in `get_operations()`:
```python
from capabilities.base import Capability, Operation, ExecutionResult
from security.risk import RiskLevel

class MyCustomCapability(Capability):
    name = "custom"
    description = "Description of capability for the LLM planner"

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="do_something",
                description="What this operation does",
                parameters={"param": {"type": "string"}},
                default_risk=RiskLevel.LOW,
                handler=self.do_something,
            )
        ]

    def do_something(self, param: str) -> ExecutionResult:
        # 1. Perform REAL action
        # 2. Verify state
        # 3. Return ExecutionResult with evidence
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="do_something",
            evidence={"param": param},
            verification={"completed": True},
        )
```
3. Register the capability in `capabilities/__init__.py`.

---

## Running Tests

Run all unit tests:
```bash
python3 -m unittest discover -s tests -v
```
