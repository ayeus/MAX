"""CLI interface for MAX — Local General-Purpose Computer Agent for macOS."""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from agent.core import AgentCore
from app.diagnostics import run_system_diagnostics
from memory.memories import memory_manager
from memory.preferences import preference_manager
from security.permissions import check_macos_permissions, PermissionStatus
from app.config import settings
from memory.workflows import workflow_manager
from voice.tts import speak_text, list_available_voices
from voice.recorder import record_microphone
from voice.whisper_stt import transcribe_audio, is_whisper_available

app = typer.Typer(help="MAX — Local General-Purpose AI Computer Agent for macOS", no_args_is_help=True)
console = Console()


@app.command()
def text(
    request: str = typer.Argument(..., help="Natural-language outcome request describing what you want your Mac to do"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Show detailed execution steps and timing"),
):
    """Execute an arbitrary computer outcome request using natural language."""
    console.print(f"\n[bold cyan]▶ MAX Computer Agent[/bold cyan] — Request: [bold white]\"{request}\"[/bold white]\n")

    agent = AgentCore()
    with console.status("[bold green]Observing environment and formulating plan...[/bold green]", spinner="dots"):
        report = agent.run(request, debug=debug)

    # Strategy / Thought
    console.print(Panel(f"[bold italic]{report.thought}[/bold italic]", title="[bold blue]Strategy[/bold blue]", border_style="blue"))

    # Executed Steps Table
    table = Table(title="Execution Evidence", show_header=True, header_style="bold magenta")
    table.add_column("Step", style="dim", width=6)
    table.add_column("Capability", style="cyan", width=14)
    table.add_column("Action", style="green", width=22)
    table.add_column("Status", width=10)
    table.add_column("Evidence / Output", style="white")

    for rec in report.steps_executed:
        status_str = "[green]✓ Success[/green]" if rec.result.success else "[red]✗ Failed[/red]"
        evidence_text = ""
        if rec.step.capability == "terminal":
            out = rec.result.data.get("stdout", "").strip() or rec.result.data.get("stderr", "").strip()
            evidence_text = out[:250] + ("..." if len(out) > 250 else "")
        elif rec.step.capability == "applications":
            app_name = rec.result.data.get("application", "")
            running = rec.result.verification.get("process_present_in_process_list", False)
            evidence_text = f"App: {app_name} (Running: {running})"
        elif rec.step.capability == "filesystem":
            if "matches_count" in rec.result.data:
                evidence_text = f"{rec.result.data['matches_count']} matches found"
            elif "lines_read" in rec.result.data:
                evidence_text = f"Read {rec.result.data['lines_read']} lines"
            else:
                evidence_text = str(rec.result.data)[:250]
        else:
            evidence_text = str(rec.result.data)[:250]

        table.add_row(
            str(rec.step.step_number),
            rec.step.capability,
            rec.step.action,
            status_str,
            evidence_text or "(completed)",
        )

    console.print(table)

    # Factual Summary
    summary_color = "green" if report.overall_success else "yellow"
    console.print(Panel(report.final_summary, title=f"[bold {summary_color}]Factual Outcome[/bold {summary_color}]", border_style=summary_color))

    # Limitations or Permission Warnings
    if report.limitations:
        lim_tree = Tree("[bold red]Limitations / Diagnostic Notices[/bold red]")
        for lim in report.limitations:
            lim_tree.add(f"[red]{lim}[/red]")
        console.print(lim_tree)


@app.command()
def debug(
    request: str = typer.Argument(..., help="Natural-language outcome request to trace in developer mode"),
):
    """Run an outcome in Developer Mode, displaying structured execution traces."""
    console.print(f"\n[bold yellow]🔍 DEVELOPER MODE EXECUTION TRACE[/bold yellow]: [bold white]\"{request}\"[/bold white]\n")
    agent = AgentCore()
    report = agent.run(request, debug=True)

    console.print(f"[bold cyan]Strategy Thought:[/bold cyan] {report.thought}\n")

    for idx, rec in enumerate(report.steps_executed, 1):
        step_panel = (
            f"[bold]Capability:[/bold] {rec.step.capability}\n"
            f"[bold]Action:[/bold] {rec.step.action}\n"
            f"[bold]Arguments:[/bold] {rec.step.args}\n"
            f"[bold]Duration:[/bold] {rec.result.duration_ms:.1f}ms\n"
            f"[bold]Success:[/bold] {rec.result.success}\n"
            f"[bold]Verification Details:[/bold] {rec.result.verification}\n"
            f"[bold]Evidence Data:[/bold] {rec.result.evidence}\n"
            f"[bold]Post Observation:[/bold] {rec.observation_after}"
        )
        border = "green" if rec.result.success else "red"
        console.print(Panel(step_panel, title=f"Step {idx}: {rec.step.capability}.{rec.step.action}", border_style=border))

    console.print(f"\n[bold]Final Outcome:[/bold]\n{report.final_summary}\n")


@app.command()
def doctor():
    """Run comprehensive diagnostics of macOS hardware, Ollama, models, and permissions."""
    console.print("\n[bold cyan]🩺 MAX macOS Environment Diagnostics[/bold cyan]\n")
    diag = run_system_diagnostics()

    # Hardware & System Table
    sys_table = Table(title="System & Hardware", show_header=False)
    sys_table.add_column("Property", style="bold cyan", width=24)
    sys_table.add_column("Value", style="white")

    sys_table.add_row("Architecture", diag.architecture)
    sys_table.add_row("Processor", diag.cpu_brand)
    sys_table.add_row("Total RAM", f"{diag.ram_gb} GB ({diag.ram_bytes:,} bytes)")
    sys_table.add_row("macOS Version", f"{diag.macos_product} {diag.macos_version} (Build {diag.macos_build})")
    sys_table.add_row("Current User", diag.current_user)
    sys_table.add_row("Default Shell", diag.current_shell)
    sys_table.add_row("Working Directory", diag.cwd)
    console.print(sys_table)

    # Ollama Status
    ollama_table = Table(title="Ollama & Local Models", show_header=False)
    ollama_table.add_column("Property", style="bold cyan", width=24)
    ollama_table.add_column("Value", style="white")

    status_badge = "[bold green]Online & Responding[/bold green]" if diag.ollama_running else "[bold red]Offline / Unreachable[/bold red]"
    ollama_table.add_row("Ollama Service", f"{settings.ollama_base_url} ({status_badge})")
    ollama_table.add_row("Configured Reasoning Model", settings.reasoning_model)
    ollama_table.add_row("Installed Local Models", ", ".join(diag.ollama_models) if diag.ollama_models else "None detected")
    console.print(ollama_table)

    # Permissions
    perm_table = Table(title="macOS Privacy & Security Permissions", show_header=True, header_style="bold magenta")
    perm_table.add_column("Permission", style="cyan", width=20)
    perm_table.add_column("Status", width=22)
    perm_table.add_column("Setting Location / Impact", style="white")

    for p in diag.permissions:
        status_text = "[bold green]✓ GRANTED[/bold green]" if p.status == PermissionStatus.GRANTED else "[bold yellow]⚠️ MISSING / DENIED[/bold yellow]"
        perm_table.add_row(
            p.permission_name,
            status_text,
            f"{p.system_settings_path}\n↳ {p.impact}",
        )
    console.print(perm_table)

    # Tools Table
    tool_table = Table(title="Toolchains & CLI Binaries", show_header=True, header_style="bold magenta")
    tool_table.add_column("Tool", style="cyan", width=16)
    tool_table.add_column("Status", width=14)
    tool_table.add_column("Path", style="dim", width=36)
    tool_table.add_column("Version", style="white")

    for name, st in diag.tools.items():
        st_text = "[green]Installed[/green]" if st.installed else "[dim]Not Found[/dim]"
        tool_table.add_row(name, st_text, st.path or "-", st.version or "-")
    console.print(tool_table)


@app.command()
def memory(
    action: str = typer.Argument("list", help="Action: list, set, get, forget, or clear"),
    key: str = typer.Option(None, "--key", "-k", help="Memory key"),
    value: str = typer.Option(None, "--value", "-v", help="Memory content or value"),
):
    """View and manage persistent memories and user preferences."""
    act = action.lower()
    if act == "list":
        mems = memory_manager.list_memories()
        prefs = preference_manager.list_preferences()

        mem_table = Table(title="Explicit Memories", show_header=True, header_style="bold cyan")
        mem_table.add_column("Key", style="bold white", width=20)
        mem_table.add_column("Content", style="green")
        mem_table.add_column("Updated", style="dim", width=22)
        for m in mems:
            mem_table.add_row(m.key, m.content, m.updated_at)
        console.print(mem_table)

        pref_table = Table(title="User Preferences", show_header=True, header_style="bold magenta")
        pref_table.add_column("Key", style="bold white", width=20)
        pref_table.add_column("Value", style="green")
        for k, v in prefs.items():
            pref_table.add_row(k, v)
        console.print(pref_table)

    elif act == "remember":
        if not key or not value:
            console.print("[red]Error: --key and --value are required for 'remember'[/red]")
            raise typer.Exit(1)
        saved = memory_manager.remember(key, value)
        console.print(f"[green]✓ Memory saved: '{key}'[/green]" if saved else "[red]Failed to save memory.[/red]")

    elif act == "forget":
        if not key:
            console.print("[red]Error: --key is required for 'forget'[/red]")
            raise typer.Exit(1)
        forgot = memory_manager.forget(key)
        console.print(f"[green]✓ Memory removed: '{key}'[/green]" if forgot else f"[yellow]No memory found for '{key}'[/yellow]")

    elif act == "clear":
        count = memory_manager.clear_memories()
        console.print(f"[yellow]Cleared {count} memories.[/yellow]")


@app.command()
def speak(
    text: str = typer.Argument(..., help="Text to speak out loud using macOS speech synthesis"),
    voice: str = typer.Option(None, "--voice", "-v", help="Voice name (e.g. 'Samantha', 'Albert', 'Daniel')"),
):
    """Speak text out loud using native macOS speech synthesis."""
    console.print(f"[bold cyan]🗣️  Speaking:[/bold cyan] \"{text}\"")
    res = speak_text(text, voice=voice)
    if res.success:
        console.print(f"[green]✓ Completed speech in {res.duration_ms:.1f}ms[/green]")
    else:
        console.print(f"[red]Speech failed: {res.error}[/red]")


@app.command()
def voices():
    """List all available speech synthesis voices installed in macOS."""
    all_voices = list_available_voices()
    table = Table(title="macOS Installed Speech Voices", show_header=True, header_style="bold magenta")
    table.add_column("Voice Name", style="bold cyan", width=18)
    table.add_column("Locale", style="green", width=12)
    table.add_column("Sample Text", style="white")

    for v in all_voices[:30]:  # Show first 30 voices
        table.add_row(v.name, v.locale, v.sample_text)
    console.print(table)
    console.print(f"[dim]Total {len(all_voices)} voices available.[/dim]")


@app.command()
def voice(
    duration: float = typer.Option(4.0, "--duration", "-d", help="Audio recording duration in seconds"),
    speak_response: bool = typer.Option(True, "--speak/--no-speak", help="Speak the result summary via TTS"),
):
    """Push-to-talk interactive voice interface for MAX."""
    console.print("\n[bold cyan]🎙️  MAX Voice Interface[/bold cyan]")

    if not is_whisper_available():
        console.print("[yellow]⚠️  Local Whisper STT is not installed.[/yellow]")
        console.print("You can speak with MAX using push-to-talk once Whisper is installed (`pip install openai-whisper`).")
        console.print("In the meantime, enter your outcome request below:\n")
        try:
            req = input("MAX > ").strip()
            if req:
                agent = AgentCore()
                report = agent.run(req)
                console.print(Panel(report.final_summary, title="Outcome", border_style="green"))
                if speak_response:
                    speak_text(report.final_summary)
        except (KeyboardInterrupt, EOFError):
            console.print("\nAborted.")
        return

    console.print(f"[bold green]Recording audio from microphone for {duration} seconds... Speak now![/bold green]")
    rec = record_microphone(duration_seconds=duration)
    if not rec.success:
        console.print(f"[red]Failed to record audio: {rec.error}[/red]")
        return

    console.print("[dim]Transcribing audio with local Whisper...[/dim]")
    stt = transcribe_audio(rec.wav_path)
    if not stt.success or not stt.text:
        console.print(f"[yellow]Could not transcribe audio: {stt.error or 'No speech detected.'}[/yellow]")
        return

    console.print(f"[bold white]You said:[/bold white] \"{stt.text}\"\n")
    agent = AgentCore()
    report = agent.run(stt.text)
    console.print(Panel(report.final_summary, title="Outcome", border_style="green"))
    if speak_response:
        speak_text(report.final_summary)


@app.command()
def workflow(
    action: str = typer.Argument("list", help="Action: list, run, or show"),
    name: str = typer.Option(None, "--name", "-n", help="Workflow name"),
):
    """View and replay saved workflow procedures."""
    act = action.lower()
    if act == "list":
        wfs = workflow_manager.list_workflows()
        table = Table(title="Saved Reusable Workflows", show_header=True, header_style="bold cyan")
        table.add_column("Workflow Name", style="bold white", width=22)
        table.add_column("Description", style="green")
        table.add_column("Created", style="dim", width=22)

        for w in wfs:
            table.add_row(w["name"], w["description"], w["created_at"])
        console.print(table)
        console.print(f"[dim]{len(wfs)} workflows saved in ~/.max/workflows/[/dim]")

    elif act == "run":
        if not name:
            console.print("[red]Error: --name is required for 'workflow run'[/red]")
            raise typer.Exit(1)
        console.print(f"\n[bold cyan]▶ Replaying Workflow:[/bold cyan] [bold white]{name}[/bold white]")
        rep = workflow_manager.execute_workflow(name)
        if rep.success:
            console.print(f"[bold green]✓ Workflow '{name}' completed successfully ({len(rep.results)} steps).[/bold green]")
        else:
            console.print(f"[bold red]✗ Workflow '{name}' encountered errors.[/bold red]")

    elif act == "show":
        if not name:
            console.print("[red]Error: --name is required for 'workflow show'[/red]")
            raise typer.Exit(1)
        wf = workflow_manager.get_workflow(name)
        if not wf:
            console.print(f"[red]Workflow '{name}' not found.[/red]")
            raise typer.Exit(1)
        console.print(Panel(wf.model_dump_json(indent=2), title=f"Workflow: {wf.name}", border_style="cyan"))


if __name__ == "__main__":
    app()
