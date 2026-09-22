"""Dynamic risk assessment engine for MAX computer agent.

Classifies commands, file operations, and system actions into:
- SAFE: Harmless read-only inspection
- LOW: Standard non-destructive user operations (e.g. creating a test file)
- MEDIUM: Package installs, build commands, minor configuration changes
- HIGH: Recursive deletions, force pushes, privilege escalation, mass modifications (Requires user confirmation)
- BLOCKED: Catastrophic destruction (e.g. wiping disks, destroying OS root /System)
"""

from enum import Enum
from pathlib import Path
from pydantic import BaseModel
import re
import shlex


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKED = "BLOCKED"


class RiskAssessment(BaseModel):
    level: RiskLevel
    reason: str
    requires_confirmation: bool = False
    affected_targets: list[str] = []


PROTECTED_SYSTEM_PATHS = [
    Path("/System"),
    Path("/Library"),
    Path("/usr/bin"),
    Path("/usr/sbin"),
    Path("/bin"),
    Path("/sbin"),
    Path("/private/etc"),
    Path("/etc"),
    Path("/dev"),
]

BLOCKED_PATTERNS = [
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+/\s*$", "Attempted deletion of operating system root /"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(~|\$HOME)\s*$", "Attempted recursive deletion of user home root"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+/\*", "Attempted wildcard deletion of root directory"),
    (r"\bmkfs\b", "Disk formatting tool detected"),
    (r"\bdiskutil\s+(eraseDisk|partitionDisk)\b", "Destructive disk partition/erasure detected"),
    (r"\bdd\s+if=.*of=/dev/(r?disk|null)", "Direct raw disk write detected"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "Fork bomb detected"),
    (r"\bcurl\s+[^|]+\|\s*(sudo\s+)?(bash|sh|zsh)\b", "Piping unverified remote web content directly to shell"),
    (r"\bwget\s+[^|]+\|\s*(sudo\s+)?(bash|sh|zsh)\b", "Piping unverified remote web content directly to shell"),
]

HIGH_RISK_PATTERNS = [
    (r"\bsudo\b", "Command requests administrative root privileges (sudo)"),
    (r"\brm\s+-[a-zA-Z]*r", "Recursive file/directory deletion"),
    (r"\brm\s+", "File deletion"),
    (r"\bgit\s+reset\s+--hard\b", "Destructive git reset --hard discards all uncommitted work"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f[a-zA-Z]*\b", "Destructive git clean forces unversioned file removal"),
    (r"\bgit\s+push\s+.*--force\b", "Force pushing to remote repository can overwrite commits"),
    (r"\bchmod\s+-[a-zA-Z]*R\s+777\b", "Recursive permissive permissions (777) creates security hazard"),
    (r"\bkillall\s+-9\b", "Forcefully killing processes by name"),
    (r"\bkill\s+-9\s+1\b", "Attempted kill of init/launchd process"),
    (r"\bshutdown\b|\breboot\b", "System power command"),
]

MEDIUM_RISK_PATTERNS = [
    (r"\bpip\s+install\b|\bpip3\s+install\b", "Installing Python package"),
    (r"\bnpm\s+install\b|\byarn\s+add\b|\bpnpm\s+add\b", "Installing Node package"),
    (r"\bbrew\s+install\b", "Installing Homebrew formula"),
    (r"\bgit\s+(commit|merge|rebase|stash)\b", "Git state modifying operation"),
    (r"\bkill\b|\bpkill\b", "Terminating running process"),
    (r"\bchmod\b|\bchown\b", "Modifying file permissions or ownership"),
    (r"\bmv\b", "Moving/renaming file or directory"),
]

SAFE_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "rg", "find", "which", "where", "pwd",
    "echo", "printf", "sw_vers", "uname", "sysctl", "ps", "top", "df", "du",
    "whoami", "id", "uptime", "date", "file", "stat", "git status", "git log",
    "git diff", "git branch", "node -v", "node --version", "npm -v", "npm --version",
    "python -v", "python --version", "python3 --version", "python3 -V", "pip list",
    "brew list", "docker --version", "docker ps", "ollama list", "open -a"
}


def assess_path_risk(path: Path | str) -> RiskAssessment:
    """Assess whether a file path falls into a protected operating system zone."""
    resolved = Path(path).expanduser().resolve()

    # Check root wiping
    if resolved == Path("/"):
        return RiskAssessment(
            level=RiskLevel.BLOCKED,
            reason="Operating system root directory / cannot be targeted directly.",
            affected_targets=[str(resolved)],
        )

    # Check user home root
    if resolved == Path.home():
        return RiskAssessment(
            level=RiskLevel.HIGH,
            reason="Direct modification or deletion of user home root directory.",
            requires_confirmation=True,
            affected_targets=[str(resolved)],
        )

    # Check protected OS system paths
    for protected in PROTECTED_SYSTEM_PATHS:
        if protected == Path("/"):
            continue
        try:
            if resolved == protected or protected in resolved.parents:
                return RiskAssessment(
                    level=RiskLevel.BLOCKED,
                    reason=f"Path {resolved} is inside protected macOS system location {protected}.",
                    affected_targets=[str(resolved)],
                )
        except Exception:
            pass

    return RiskAssessment(
        level=RiskLevel.SAFE,
        reason="Path is in standard user-writable workspace.",
        affected_targets=[str(resolved)],
    )


def analyze_command_structure(cmd: str) -> list[str]:
    """Inspect structured shell constructs beyond regex: operators, pipes, redirects, subshells."""
    features = []
    if re.search(r"(&&|\|\||;)", cmd):
        features.append("chained_commands")
    if "|" in cmd:
        features.append("pipe_operator")
    if re.search(r"(>>|>|<)", cmd):
        features.append("redirection")
    if re.search(r"(\$\(|\`)", cmd):
        features.append("subshell_command_substitution")
    if re.search(r"\b(eval|exec)\b", cmd):
        features.append("dynamic_evaluation")
    if re.search(r"\b(base64\s+-d|xxd\s+-r)\b", cmd):
        features.append("encoded_payload")
    if re.search(r"\bsudo\b", cmd):
        features.append("sudo_privilege_escalation")
    return features


def assess_command_risk(command_str: str) -> RiskAssessment:
    """Analyze a shell command string for dangerous actions, structural patterns, and security risks."""
    cmd = command_str.strip()
    if not cmd:
        return RiskAssessment(level=RiskLevel.SAFE, reason="Empty command")

    # 1. Check BLOCKED patterns first
    for pattern, reason in BLOCKED_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return RiskAssessment(
                level=RiskLevel.BLOCKED,
                reason=reason,
                requires_confirmation=False,
                affected_targets=[cmd],
            )

    # 2. Structured Analysis Checks
    struct_features = analyze_command_structure(cmd)
    if "encoded_payload" in struct_features and ("pipe_operator" in struct_features or "subshell_command_substitution" in struct_features):
        return RiskAssessment(
            level=RiskLevel.BLOCKED,
            reason="Piping encoded payload directly into shell execution is blocked.",
            requires_confirmation=False,
            affected_targets=[cmd],
        )

    if "dynamic_evaluation" in struct_features and "sudo_privilege_escalation" in struct_features:
        return RiskAssessment(
            level=RiskLevel.BLOCKED,
            reason="Dynamic shell evaluation with sudo privileges is blocked.",
            requires_confirmation=False,
            affected_targets=[cmd],
        )

    # 3. Check HIGH risk patterns
    for pattern, reason in HIGH_RISK_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return RiskAssessment(
                level=RiskLevel.HIGH,
                reason=reason,
                requires_confirmation=True,
                affected_targets=[cmd],
            )

    # If subshell or dynamic evaluation is present, treat as HIGH risk
    if "dynamic_evaluation" in struct_features:
        return RiskAssessment(
            level=RiskLevel.HIGH,
            reason="Command contains dynamic shell evaluation (eval/exec).",
            requires_confirmation=True,
            affected_targets=[cmd],
        )

    # 4. Check MEDIUM risk patterns
    for pattern, reason in MEDIUM_RISK_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return RiskAssessment(
                level=RiskLevel.MEDIUM,
                reason=reason,
                requires_confirmation=False,
                affected_targets=[cmd],
            )

    # Check tokens for path risks in arguments
    try:
        tokens = shlex.split(cmd)
        for token in tokens[1:]:
            if token.startswith("/") or token.startswith("~"):
                path_eval = assess_path_risk(token)
                if path_eval.level in (RiskLevel.BLOCKED, RiskLevel.HIGH):
                    return RiskAssessment(
                        level=path_eval.level,
                        reason=f"Command references sensitive path: {path_eval.reason}",
                        requires_confirmation=path_eval.requires_confirmation,
                        affected_targets=[token],
                    )
    except Exception:
        pass

    # Check if command is in safe commands list
    for safe in SAFE_COMMANDS:
        if cmd == safe or cmd.startswith(safe + " "):
            return RiskAssessment(
                level=RiskLevel.SAFE,
                reason="Standard read-only or inspection command",
                requires_confirmation=False,
                affected_targets=[cmd],
            )

    # Default to LOW risk for normal execution
    return RiskAssessment(
        level=RiskLevel.LOW,
        reason="Standard operation",
        requires_confirmation=False,
        affected_targets=[cmd],
    )
