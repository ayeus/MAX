"""Planning prompt constructor for MAX."""

import json


def build_planning_prompt(
    user_request: str,
    environment_context: dict,
    capabilities_schema: list[dict],
    recent_history: list[dict] | None = None,
) -> str:
    """Build prompt to guide LLM in generating an executable plan."""
    prompt_parts = [
        "### CURRENT LIVE ENVIRONMENT STATE:",
        json.dumps(environment_context, indent=2),
        "",
        "### AVAILABLE SYSTEM CAPABILITIES & OPERATIONS:",
        json.dumps(capabilities_schema, indent=2),
        "",
    ]

    if recent_history:
        prompt_parts.extend([
            "### RECENT CONVERSATION / TASK CONTEXT:",
            json.dumps(recent_history, indent=2),
            "",
        ])

    prompt_parts.extend([
        "### USER DESIRED OUTCOME:",
        f'"{user_request}"',
        "",
        "Construct the optimal execution plan to achieve this outcome on macOS using the available capabilities.",
        "IMPORTANT RULES:",
        "- When executing ANY shell command (e.g. git, npm, python, brew, docker, ls, curl, etc.), use:",
        '  capability: "terminal", action: "execute_command", args: {"command": "<exact shell command string>"}',
        "- When launching applications, use capability: 'applications', action: 'launch_application', args: {'application_name': '...'}",
        "- When searching the web or opening a URL in browser, use capability: 'browser', action: 'search_web' (args: {'query': '...'}) or action: 'open_url' (args: {'url': '...'}),",
        "- When inspecting active window or GUI menus, use capability: 'accessibility', action: 'get_active_window_info' or 'list_menu_items',",
        "- When visually inspecting what is on screen, reading errors/dialogs on screen, or locating/clicking visual controls when semantic accessibility is unavailable, use capability: 'vision', action: 'describe_screen', 'ask_screen', or 'visual_click',",
        "- When inspecting the filesystem, use capability: 'filesystem', action: 'find_files' or 'list_directory' or 'read_file'",
        "- Use ONLY the operations declared in the capability schemas above.",
        "Output ONLY the JSON object with 'thought' and 'plan' fields as specified in your system prompt.",
    ])

    return "\n".join(prompt_parts)
