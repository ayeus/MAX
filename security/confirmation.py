"""User confirmation handler for high-risk actions in MAX.

Adheres strictly to the binary confirmation requirement:
- Accepts only 'y' or 'yes' (case-insensitive) as affirmative.
- Anything else is treated as cancel/rejection.
- Clear, specific context of what will happen.
"""

from rich.console import Console
from rich.panel import Panel

console = Console()


def request_user_confirmation(action_description: str, targets: list[str] | None = None) -> bool:
    """Prompt user interactively in the terminal to confirm a high-risk operation.

    Returns True only if the user explicitly enters 'y' or 'yes'.
    """
    target_info = ""
    if targets:
        target_info = "\nAffected targets:\n" + "\n".join(f"  • {t}" for t in targets)

    prompt_text = (
        f"[bold yellow]⚠️  HIGH-RISK OPERATION CONFIRMATION REQUIRED[/bold yellow]\n\n"
        f"{action_description}{target_info}\n\n"
        f"[bold white]Do you want to continue? [y/N]: [/bold white]"
    )

    console.print(Panel(prompt_text, border_style="yellow"))

    try:
        response = input().strip().lower()
        if response in ("y", "yes"):
            console.print("[green]✓ Operation confirmed by user.[/green]")
            return True
        else:
            console.print("[red]✗ Operation cancelled by user.[/red]")
            return False
    except (EOFError, KeyboardInterrupt):
        console.print("\n[red]✗ Operation aborted.[/red]")
        return False
