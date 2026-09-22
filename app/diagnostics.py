"""Real environment and hardware diagnostic inspection for MAX.

Queries the macOS operating system, hardware, Ollama, permissions, and toolchains directly.
Never hardcodes machine specifications or environment status.
"""

from pathlib import Path
from pydantic import BaseModel
import json
import os
import platform
import shutil
import urllib.request
from app.config import settings
from macos.shell import run_shell_command
from security.permissions import check_macos_permissions, PermissionReport
from tasks.manager import task_manager


class ToolStatus(BaseModel):
    name: str
    installed: bool
    path: str | None = None
    version: str | None = None


class SystemDiagnostics(BaseModel):
    architecture: str
    ram_bytes: int
    ram_gb: float
    cpu_brand: str
    macos_product: str
    macos_version: str
    macos_build: str
    current_shell: str
    current_user: str
    home_dir: str
    cwd: str
    ollama_running: bool
    ollama_models: list[str]
    permissions: list[PermissionReport]
    tools: dict[str, ToolStatus]
    active_tasks_count: int = 0
    tasks_log_dir: str = ""


def get_tool_version(tool_name: str, path: str) -> str | None:
    """Query real tool version using standard CLI flags."""
    version_commands = {
        "python3": f"{path} --version",
        "node": f"{path} -v",
        "npm": f"{path} -v",
        "git": f"{path} --version",
        "brew": f"{path} --version",
        "docker": f"{path} --version",
        "ollama": f"{path} --version",
        "osascript": f"{path} -e 'return 1'",
        "tesseract": f"{path} --version",
        "jq": f"{path} --version",
        "curl": f"{path} --version",
        "whisper": f"{path} --help",
    }
    cmd = version_commands.get(tool_name, f"{path} --version")
    res = run_shell_command(cmd, timeout=4)
    if res.exit_code == 0 or res.stdout.strip():
        first_line = (res.stdout.strip() or res.stderr.strip()).split("\n")[0]
        return first_line.strip()
    return None


def run_system_diagnostics() -> SystemDiagnostics:
    """Query the live macOS machine for hardware, software, and permissions state."""
    # Architecture and hardware
    arch = platform.machine()
    res_mem = run_shell_command("/usr/sbin/sysctl -n hw.memsize", timeout=3)
    ram_bytes = int(res_mem.stdout.strip()) if res_mem.stdout.strip().isdigit() else 0
    ram_gb = round(ram_bytes / (1024 ** 3), 2)

    res_cpu = run_shell_command("/usr/sbin/sysctl -n machdep.cpu.brand_string", timeout=3)
    cpu_brand = res_cpu.stdout.strip() or "Apple Silicon"

    # macOS version
    res_sw = run_shell_command("/usr/bin/sw_vers", timeout=3)
    sw_dict = {}
    for line in res_sw.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            sw_dict[k.strip()] = v.strip()

    macos_product = sw_dict.get("ProductName", "macOS")
    macos_version = sw_dict.get("ProductVersion", platform.mac_ver()[0])
    macos_build = sw_dict.get("BuildVersion", "")

    # Shell and user
    current_shell = os.getenv("SHELL", "/bin/zsh")
    current_user = os.getenv("USER", "unknown")
    home_dir = str(Path.home())
    cwd = str(Path.cwd())

    # Ollama connectivity & models
    ollama_running = False
    ollama_models: list[str] = []
    try:
        req = urllib.request.Request(f"{settings.ollama_base_url}/api/tags", headers={"User-Agent": "MAX-Agent"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                ollama_running = True
                ollama_models = [m["name"] for m in data.get("models", [])]
    except Exception:
        ollama_running = False

    # Permissions
    permissions = check_macos_permissions()

    # Tools check
    tools_to_check = [
        "python3", "node", "npm", "git", "brew", "docker",
        "ollama", "osascript", "tesseract", "jq", "curl", "whisper"
    ]
    tools_status: dict[str, ToolStatus] = {}
    for tool in tools_to_check:
        found_path = shutil.which(tool)
        if found_path:
            version = get_tool_version(tool, found_path)
            tools_status[tool] = ToolStatus(
                name=tool,
                installed=True,
                path=found_path,
                version=version,
            )
        else:
            tools_status[tool] = ToolStatus(
                name=tool,
                installed=False,
                path=None,
                version=None,
            )

    return SystemDiagnostics(
        architecture=arch,
        ram_bytes=ram_bytes,
        ram_gb=ram_gb,
        cpu_brand=cpu_brand,
        macos_product=macos_product,
        macos_version=macos_version,
        macos_build=macos_build,
        current_shell=current_shell,
        current_user=current_user,
        home_dir=home_dir,
        cwd=cwd,
        ollama_running=ollama_running,
        ollama_models=ollama_models,
        permissions=permissions,
        tools=tools_status,
        active_tasks_count=len([t for t in task_manager.list_tasks() if t.is_active]),
        tasks_log_dir=str(settings.base_dir / "logs" / "tasks"),
    )
