# MAX Security Model & Policy

Security is a foundational subsystem of MAX, not an afterthought. Because MAX operates as an autonomous computer operator with broad system access, security is enforced through layered boundaries, risk classification, user confirmation, and tamper-evident audit logging.

---

## 1. Dynamic Risk Classification

Every action is evaluated by `security.risk.assess_command_risk` and `security.risk.assess_path_risk`:

| Risk Level | Definition | Behavior |
| :--- | :--- | :--- |
| **`SAFE`** | Read-only inspection (`ls`, `git status`, `sw_vers`, `pwd`, etc.) | Executes autonomously |
| **`LOW`** | Standard benign operations (creating a workspace file, testing a tool) | Executes autonomously |
| **`MEDIUM`** | Package installations (`pip install`, `npm install`), git commits, moving files | Executes autonomously with audit logging |
| **`HIGH`** | Recursive deletions (`rm -rf`), `sudo`, `git clean -fd`, `git reset --hard`, force pushes | **Requires explicit interactive user confirmation (`y/N`)** |
| **`BLOCKED`** | Catastrophic destruction (`rm -rf /`, `rm -rf ~`, `mkfs`, raw disk writes, piping web curls to shell) | **Unconditionally blocked** |

---

## 2. Protected System Paths
The following locations are safeguarded against destructive actions:
- `/` (Filesystem root)
- `/System`
- `/Library`
- `/usr/bin`, `/usr/sbin`
- `/bin`, `/sbin`
- `/private/etc`, `/etc`
- `/dev`

Temporary user workspaces (`/tmp`, `/private/tmp`, `/var/folders`) remain accessible for standard scratch execution.

---

## 3. Reversibility Principle
Whenever removing files or cleaning directories, MAX prefers reversible operations:
* Deleting files uses `filesystem.move_to_trash` via macOS Finder AppleScript rather than unrecoverable `rm`.
* Destructive operations always require user consent.

---

## 4. Tamper-Evident Audit Trail
All tool requests, risk assessments, user confirmations, execution durations, and verification results are appended in structured JSONL format to:
```text
~/.max/audit.jsonl
```
This log enables complete post-execution inspection and security auditing.
