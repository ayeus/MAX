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
        "- When executing shell commands (e.g. echo, mkdir, cp, touch, git, npm, python, brew, docker, ls, curl, etc.), use:",
        '  capability: "terminal", action: "execute_command", args: {"command": "<exact shell command string>"}',
        "- ONLY use capability: 'tasks', action: 'start_background_task' when the user explicitly asks to run something in the background or as a background service/daemon.",
        "- When monitoring a directory for file changes, use capability: 'tasks', action: 'watch_directory', args: {'path': '<directory path>'}",
        "- When monitoring a network port for service readiness, use capability: 'tasks', action: 'monitor_port', args: {'port': <port number>}",
        "- When checking or listing background tasks, use capability: 'tasks', action: 'list_tasks', args: {}",
        "- When inspecting a background task status or logs, use capability: 'tasks', action: 'get_task_status' or 'get_task_logs', args: {'task_id': '<task_id>'}",
        "- When terminating a background task, use capability: 'tasks', action: 'kill_task', args: {'task_id': '<task_id>'}",
        "- When launching applications, use capability: 'applications', action: 'launch_application', args: {'application_name': '...'}",
        "- When controlling applications, interacting with GUI controls, or typing inside windows:",
        "  * To inspect the active window and its interactive controls: capability: 'accessibility', action: 'get_computer_state', args: {}",
        "  * To locate and click a button, link, or tab: capability: 'accessibility', action: 'click_element', args: {'label': '<label or button name>', 'role': '<optional role>'}",
        "  * To type into an input field, search box, or document: capability: 'accessibility', action: 'type_into_element', args: {'text': '<text to type>', 'target_label': '<optional field label or description>', 'clear_first': false, 'press_return': false}",
        "  * To send keyboard shortcuts (e.g. Cmd+S to save, Cmd+Enter, Tab): capability: 'accessibility', action: 'send_key_chord', args: {'key': 's', 'modifiers': 'command'}",
        "  * To scroll content: capability: 'accessibility', action: 'scroll', args: {'direction': 'down' or 'up', 'amount': 5}",
        "- TYPE != SEND RULE: Drafting text into an application does NOT automatically mean sending or submitting. Only press Return or click Send/Submit if the user's explicit request instructed sending/submitting.",
        "- Multi-step computer tasks (e.g. 'Open app and type X'): Formulate the steps sequentially (e.g. launch_application -> type_into_element).",
        "- When searching the web or opening a URL in browser, use capability: 'browser', action: 'search_web' (args: {'query': '...'}) or action: 'open_url' (args: {'url': '...'}),",
        "- When visually inspecting what is on screen or locating controls without accessibility labels, use capability: 'vision', action: 'describe_screen', 'ask_screen', or 'visual_click',",
        "- When adjusting display brightness, use capability: 'macos', action: 'increase_brightness' (args: {'delta': 0.1}), action: 'decrease_brightness' (args: {'delta': 0.1}), or action: 'set_brightness' (args: {'level': <0.0 to 1.0>}).",
        "- When inspecting display brightness, use capability: 'macos', action: 'get_brightness', args: {}.",
        "- HARD CAPABILITY GATE: If the user request asks to change hardware or system configurations without a corresponding operation declared in the schemas (e.g. monitor refresh rate, display resolution, bluetooth pairing, overclocking), return an empty plan: [] and state in 'thought' that this capability is not supported.",
        "- Use ONLY the operations declared in the capability schemas above.",
        "Output ONLY the JSON object with 'thought' and 'plan' fields as specified in your system prompt.",
    ])

    return "\n".join(prompt_parts)

