"""General filesystem capability for MAX on macOS."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import os
import shutil
import time
from capabilities.base import Capability, Operation, ExecutionResult
from security.risk import RiskLevel, assess_path_risk
from security.policy import SecurityPolicy, PolicyViolation
from security.confirmation import request_user_confirmation
from security.audit import audit_log
from macos.applescript import run_applescript, escape_applescript_string
from app.config import settings


class FilesystemCapability(Capability):
    name = "filesystem"
    description = (
        "Inspect, search, read, write, move, and organize files on macOS. "
        "Supports targeted search by name/date/size and reversible deletion via Trash."
    )

    def __init__(self, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="list_directory",
                description="List files and subdirectories in a directory with file sizes and types.",
                parameters={
                    "path": {"type": "string", "description": "Directory path (defaults to current dir)"},
                    "include_hidden": {"type": "boolean", "description": "Include hidden files (starting with .)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.list_directory,
            ),
            Operation(
                name="find_files",
                description="Search for files by name pattern, extension, or modification timeframe.",
                parameters={
                    "directory": {"type": "string", "description": "Starting directory for search"},
                    "pattern": {"type": "string", "description": "Glob or name pattern (e.g. '*.py', '*.pdf')"},
                    "max_depth": {"type": "integer", "description": "Maximum directory recursion depth"},
                    "modified_within_days": {"type": "integer", "description": "Filter files modified within last N days"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.find_files,
            ),
            Operation(
                name="read_file",
                description="Read content of a text file on the local filesystem.",
                parameters={
                    "path": {"type": "string", "description": "Path to file"},
                    "max_lines": {"type": "integer", "description": "Maximum lines to read (default 200)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.read_file,
            ),
            Operation(
                name="write_file",
                description="Create or update a text file at a specified path.",
                parameters={
                    "path": {"type": "string", "description": "Path to file to write"},
                    "content": {"type": "string", "description": "Text content to write"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.write_file,
            ),
            Operation(
                name="move_file",
                description="Move or rename a file or directory to a new location.",
                parameters={
                    "source": {"type": "string", "description": "Source path"},
                    "destination": {"type": "string", "description": "Destination path"},
                },
                default_risk=RiskLevel.MEDIUM,
                handler=self.move_file,
            ),
            Operation(
                name="move_to_trash",
                description="Safely and reversibly move a file or folder to macOS Trash.",
                parameters={
                    "path": {"type": "string", "description": "Path to move to Trash"},
                },
                default_risk=RiskLevel.HIGH,
                handler=self.move_to_trash,
            ),
            Operation(
                name="get_metadata",
                description="Get detailed metadata (size, timestamps, permissions) for a file or directory.",
                parameters={
                    "path": {"type": "string", "description": "Path to inspect"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.get_metadata,
            ),
        ]

    def list_directory(self, path: str = ".", include_hidden: bool = False) -> ExecutionResult:
        dir_path = Path(path).expanduser().resolve()
        if not dir_path.exists() or not dir_path.is_dir():
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="list_directory",
                error=f"Directory '{dir_path}' does not exist or is not a directory.",
            )

        entries = []
        try:
            for item in dir_path.iterdir():
                if not include_hidden and item.name.startswith("."):
                    continue
                try:
                    stat = item.stat()
                    entries.append({
                        "name": item.name,
                        "is_dir": item.is_dir(),
                        "size_bytes": stat.st_size if not item.is_dir() else None,
                        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    })
                except PermissionError:
                    entries.append({"name": item.name, "is_dir": item.is_dir(), "error": "Permission denied"})
        except Exception as e:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="list_directory",
                error=str(e),
            )

        # Sort: directories first, then alphabetically
        entries.sort(key=lambda x: (not x.get("is_dir", False), x["name"].lower()))
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="list_directory",
            data={"path": str(dir_path), "count": len(entries), "entries": entries},
            evidence={"item_count": len(entries), "sample": entries[:20]},
            verification={"directory_inspected": True},
        )

    def find_files(
        self,
        directory: str = ".",
        pattern: str = "*",
        max_depth: int = 4,
        modified_within_days: int | None = None,
    ) -> ExecutionResult:
        start_dir = Path(directory).expanduser().resolve()
        if not start_dir.exists():
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="find_files",
                error=f"Directory '{start_dir}' does not exist.",
            )

        cutoff_time = None
        if modified_within_days is not None:
            cutoff_time = time.time() - (modified_within_days * 86400)

        matched_files = []
        start_depth = len(start_dir.parts)

        for root, dirs, files in os.walk(start_dir):
            current_depth = len(Path(root).parts) - start_depth
            if current_depth >= max_depth:
                dirs.clear()  # Stop descending further
                continue

            # Don't descend into hidden dirs like .git unless requested
            dirs[:] = [d for d in dirs if not d.startswith(".") or pattern.startswith(".")]

            for fname in files:
                p = Path(root) / fname
                if p.match(pattern):
                    try:
                        stat = p.stat()
                        if cutoff_time is not None and stat.st_mtime < cutoff_time:
                            continue
                        matched_files.append({
                            "path": str(p),
                            "name": fname,
                            "size_bytes": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                        })
                    except Exception:
                        pass

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="find_files",
            data={
                "directory": str(start_dir),
                "pattern": pattern,
                "matches_count": len(matched_files),
                "matches": matched_files,
            },
            evidence={"matches_count": len(matched_files), "sample": matched_files[:25]},
            verification={"search_completed": True},
        )

    def read_file(self, path: str, max_lines: int = 200) -> ExecutionResult:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists() or not file_path.is_file():
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="read_file",
                error=f"File '{file_path}' does not exist or is not a regular file.",
            )

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = []
                for _ in range(max_lines):
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line)
                content = "".join(lines)
                total_lines = len(lines)
                is_truncated = f.readline() != ""

            return ExecutionResult(
                success=True,
                capability=self.name,
                action="read_file",
                data={
                    "path": str(file_path),
                    "lines_read": total_lines,
                    "truncated": is_truncated,
                    "content": content,
                },
                evidence={"bytes_read": len(content), "lines": total_lines},
                verification={"file_read_successfully": True},
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="read_file",
                error=f"Failed to read file: {e}",
            )

    def write_file(self, path: str, content: str) -> ExecutionResult:
        file_path = Path(path).expanduser().resolve()
        try:
            self.policy.evaluate_path_access(str(file_path), is_destructive=True)
        except PolicyViolation as pv:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="write_file",
                error=str(pv),
            )

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Verification: inspect written file
            verified = file_path.exists() and file_path.stat().st_size == len(content.encode("utf-8"))
            return ExecutionResult(
                success=verified,
                capability=self.name,
                action="write_file",
                data={"path": str(file_path), "bytes_written": len(content.encode("utf-8"))},
                evidence={"path": str(file_path), "size": file_path.stat().st_size},
                verification={"file_exists": verified, "size_matches": verified},
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="write_file",
                error=f"Failed to write file: {e}",
            )

    def move_file(self, source: str, destination: str) -> ExecutionResult:
        src = Path(source).expanduser().resolve()
        dst = Path(destination).expanduser().resolve()

        # Policy checks for both source and destination
        try:
            self.policy.evaluate_path_access(str(src), is_destructive=True)
            self.policy.evaluate_path_access(str(dst), is_destructive=True)
        except PolicyViolation as pv:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="move_file",
                error=str(pv),
            )

        if not src.exists():
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="move_file",
                error=f"Source path '{src}' does not exist.",
                data={"source": str(src), "source_missing": True},
                evidence={"source_missing": True, "path": str(src)},
            )

        try:
            if dst.is_dir():
                final_dst = dst / src.name
            else:
                final_dst = dst
                final_dst.parent.mkdir(parents=True, exist_ok=True)

            shutil.move(str(src), str(final_dst))
            verified = final_dst.exists() and not src.exists()
            return ExecutionResult(
                success=verified,
                capability=self.name,
                action="move_file",
                data={"source": str(src), "destination": str(final_dst)},
                evidence={"moved_successfully": verified},
                verification={"destination_exists": final_dst.exists(), "source_removed": not src.exists()},
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="move_file",
                error=f"Failed to move file: {e}",
            )

    def move_to_trash(self, path: str) -> ExecutionResult:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="move_to_trash",
                error=f"Target path '{target}' does not exist.",
                data={"path": str(target), "already_absent": True},
                evidence={"already_absent": True, "path": str(target)},
            )

        # Policy & Confirmation check
        try:
            risk = self.policy.evaluate_path_access(str(target), is_destructive=True)
        except PolicyViolation as pv:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="move_to_trash",
                error=str(pv),
            )

        if settings.require_confirmation_for_high_risk:
            confirmed = request_user_confirmation(
                action_description=f"Move '{target}' to macOS Trash (reversible).",
                targets=[str(target)],
            )
            if not confirmed:
                return ExecutionResult(
                    success=False,
                    capability=self.name,
                    action="move_to_trash",
                    error="Cancelled by user.",
                )

        # Use macOS Finder AppleScript to send to Trash reversibly with escaped path
        escaped_target = escape_applescript_string(str(target))
        as_script = f'tell application "Finder" to delete POSIX file "{escaped_target}"'
        res = run_applescript(as_script)

        # Verification: check if target is gone from original location
        target_removed = not target.exists()
        return ExecutionResult(
            success=target_removed,
            capability=self.name,
            action="move_to_trash",
            data={"path": str(target), "applescript_output": res.stdout},
            evidence={"target_removed_from_path": target_removed},
            verification={"original_path_cleared": target_removed},
            error=res.stderr if not target_removed else None,
        )

    def get_metadata(self, path: str) -> ExecutionResult:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="get_metadata",
                error=f"Path '{p}' does not exist.",
            )

        stat = p.stat()
        meta = {
            "path": str(p),
            "is_dir": p.is_dir(),
            "is_file": p.is_file(),
            "is_symlink": p.is_symlink(),
            "size_bytes": stat.st_size,
            "permissions": oct(stat.st_mode)[-3:],
            "created": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="get_metadata",
            data=meta,
            evidence=meta,
            verification={"metadata_inspected": True},
        )
