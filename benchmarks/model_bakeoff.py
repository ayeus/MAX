"""Offline model bake-off: tool-calling accuracy + latency. Never touches the Mac.

Each case gives the model a conversation (optionally with prior tool results)
and checks the model's NEXT move: which tool it calls with which arguments,
or, for final/ask cases, that it replies in text without calling a tool.

    python -m benchmarks.model_bakeoff --models qwen3:4b,qwen2.5:7b
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

OLLAMA = "http://localhost:11434"
RESULTS_DIR = Path(__file__).parent / "results"

SYSTEM = (
    "You are MAX, an assistant that operates the user's Mac through tools.\n"
    "Rules:\n"
    "- Call ONE tool at a time, then wait for its result.\n"
    "- Only claim something is done if a tool result says status \"done\".\n"
    "- If a tool failed, say so briefly. Never pretend.\n"
    "- If required information is missing, ask a short question instead of guessing.\n"
    "- When the request is complete, reply with one short sentence and no tool call."
)


# ---------------------------------------------------------------- draft tool set

def tool(tool_name: str, desc: str, /, **params: tuple[str, str]) -> dict:
    props, required = {}, []
    for pname, (ptype, pdesc) in params.items():
        optional = pname.endswith("_")
        pname = pname.rstrip("_")
        props[pname] = {"type": ptype, "description": pdesc}
        if not optional:
            required.append(pname)
    return {"type": "function", "function": {
        "name": tool_name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


TOOLS = [
    tool("open_app", "Launch or bring an application to the front.", name=("string", "Application name")),
    tool("quit_app", "Quit an application.", name=("string", "Application name")),
    tool("switch_app", "Bring an already running application to the front.", name=("string", "Application name")),
    tool("set_volume", "Set output volume.", percent=("integer", "0-100")),
    tool("set_mute", "Mute or unmute sound output.", muted=("boolean", "true to mute")),
    tool("set_brightness", "Set display brightness to an absolute level.", percent=("integer", "0-100")),
    tool("adjust_brightness", "Change display brightness relatively.", delta_percent=("integer", "e.g. 10 or -10")),
    tool("set_clipboard", "Copy text to the clipboard.", text=("string", "Text to copy")),
    tool("list_ui", "List the interactive UI elements of the frontmost window of an app, with numeric ids.",
         app=("string", "Application name")),
    tool("click", "Click a UI element by id from list_ui.", element_id=("integer", "Element id")),
    tool("type_text", "Type text into the focused field, or into element_id if given.",
         text=("string", "Text to type"), element_id_=("integer", "Optional element id from list_ui")),
    tool("press_keys", "Press a keyboard shortcut, e.g. 'cmd+n', 'return'.", keys=("string", "Shortcut")),
    tool("create_note", "Create a note in Apple Notes.", title=("string", "Note title"), body=("string", "Note text")),
    tool("open_url", "Open a URL in the browser.", url=("string", "Full URL"), browser_=("string", "Safari or Chrome")),
    tool("web_search", "Search the web in the browser.", query=("string", "Search query")),
    tool("read_page", "Read title, URL and visible text of the current browser tab."),
    tool("run_shell", "Run a short shell command and return its output.", command=("string", "zsh command"),
         cwd_=("string", "Working directory")),
    tool("start_background", "Start a long-running command in the background.", command=("string", "zsh command"),
         cwd_=("string", "Working directory")),
    tool("read_file", "Read a text file.", path=("string", "Absolute path")),
    tool("write_file", "Create or overwrite a text file.", path=("string", "Absolute path"),
         content=("string", "File content")),
    tool("create_folder", "Create a directory (and parents).", path=("string", "Absolute path")),
    tool("move_path", "Move or rename a file or folder.", source=("string", "Absolute path"),
         destination=("string", "Absolute path")),
    tool("trash_path", "Move a file or folder to the Trash.", path=("string", "Absolute path")),
    tool("find_files", "Find files under a directory matching a glob.", directory=("string", "Absolute path"),
         pattern=("string", "Glob, e.g. *.py")),
]


# ---------------------------------------------------------------- cases

@dataclass
class Case:
    id: str
    category: str
    messages: list[dict]
    # expect(tool_name | None, args, text) -> bool.  tool_name None = text reply.
    expect: Callable[[str | None, dict, str], bool]


def user(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


def after(text: str, *steps: tuple[str, dict, dict]) -> list[dict]:
    """Conversation where the assistant already called tools and got results."""
    msgs = user(text)
    for name, args, result in steps:
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"function": {"name": name, "arguments": args}}]})
        msgs.append({"role": "tool", "content": json.dumps(result)})
    return msgs


def call(tool_name: str, /, **arg_checks: Callable[[object], bool]):
    def f(t, a, _txt):
        if t != tool_name:
            return False
        for k, pred in arg_checks.items():
            try:
                if not pred(a.get(k)):
                    return False
            except Exception:  # noqa: BLE001
                return False
        return True
    return f


def any_of(*fs):
    return lambda t, a, txt: any(f(t, a, txt) for f in fs)


def reply(pred: Callable[[str], bool] = lambda s: True):
    return lambda t, _a, txt: t is None and pred(txt.lower())


def has(*words):
    return lambda v: v is not None and all(w in str(v).lower() for w in words)


def num(target: int, tol: int = 0):
    return lambda v: v is not None and abs(int(v) - target) <= tol


DONE = {"status": "done"}
UI = {"status": "done", "elements": [
    {"id": 1, "role": "text field", "label": "Search"},
    {"id": 2, "role": "button", "label": "Send"},
    {"id": 3, "role": "text area", "label": "Message"},
]}
NEG = ("couldn", "could not", "not found", "no app", "unable", "can't", "cannot", "doesn", "failed", "isn't", "not installed")

CASES = [
    # system
    Case("open_calc", "system", user("open Calculator"), call("open_app", name=has("calculator"))),
    Case("quit_spotify", "system", user("quit Spotify"), call("quit_app", name=has("spotify"))),
    Case("volume_30", "system", user("set the volume to 30 percent"), call("set_volume", percent=num(30))),
    Case("mute", "system", user("mute the sound"), call("set_mute", muted=lambda v: v in (True, "true"))),
    Case("brighter", "system", user("make the screen a bit brighter"),
         call("adjust_brightness", delta_percent=lambda v: int(v) > 0)),
    Case("bright_20", "system", user("turn brightness down to 20%"), call("set_brightness", percent=num(20))),
    Case("switch_finder", "system", user("switch to Finder"),
         any_of(call("switch_app", name=has("finder")), call("open_app", name=has("finder")))),
    Case("clipboard", "system", user("copy the text bench-clip-42 to the clipboard"),
         call("set_clipboard", text=lambda v: v.strip() == "bench-clip-42")),
    # multi-step continuation
    Case("two_apps_1", "multistep", user("open Calculator and TextEdit"),
         any_of(call("open_app", name=has("calculator")), call("open_app", name=has("textedit")))),
    Case("two_apps_2", "multistep", after("open Calculator and TextEdit", ("open_app", {"name": "Calculator"}, DONE)),
         call("open_app", name=has("textedit"))),
    Case("two_apps_3", "multistep", after("open Calculator and TextEdit",
                                          ("open_app", {"name": "Calculator"}, DONE),
                                          ("open_app", {"name": "TextEdit"}, DONE)),
         reply()),
    # in-app
    Case("te_type_1", "in_app", user("open TextEdit and type hello from max"), call("open_app", name=has("textedit"))),
    Case("te_type_2", "in_app", after("open TextEdit and type hello from max", ("open_app", {"name": "TextEdit"}, DONE)),
         any_of(call("type_text", text=has("hello from max")), call("list_ui", app=has("textedit")),
                call("press_keys", keys=has("n")))),
    Case("ui_type", "in_app", after("type 'see you soon' in the message box", ("list_ui", {"app": "Messages"}, UI)),
         call("type_text", text=has("see you soon"), element_id=num(3))),
    Case("ui_send", "in_app", after("click send", ("list_ui", {"app": "Messages"}, UI)),
         call("click", element_id=num(2))),
    Case("note", "in_app", user("create a new note titled Groceries with the text buy milk"),
         call("create_note", title=has("groceries"), body=has("milk"))),
    Case("shortcut", "in_app", user("press command N"), call("press_keys", keys=lambda v: re.search(r"(cmd|command|⌘).*n", v.lower()))),
    # browser
    Case("open_site", "browser", user("open wikipedia.org in Safari"), call("open_url", url=has("wikipedia.org"))),
    Case("search", "browser", user("search the web for local llm benchmarks"), call("web_search", query=has("llm"))),
    Case("title_1", "browser", user("what is the title of the page open in Safari?"), call("read_page")),
    Case("title_2", "browser", after("what is the title of the page open in Safari?",
                                     ("read_page", {}, {"status": "done", "title": "Example Domain",
                                                        "url": "https://example.com", "text": "This domain is for use in examples."})),
         reply(lambda s: "example domain" in s)),
    # dev & files
    Case("mkdir", "dev_files", user("create a folder called reports in /tmp/x"),
         any_of(call("create_folder", path=has("/tmp/x/reports")), call("run_shell", command=has("mkdir", "/tmp/x/reports")))),
    Case("write", "dev_files", user("create a file named notes.txt in /tmp/x containing hello world"),
         call("write_file", path=has("/tmp/x/notes.txt"), content=has("hello world"))),
    Case("rename", "dev_files", user("rename /tmp/x/old.txt to new.txt"),
         any_of(call("move_path", source=has("/tmp/x/old.txt"), destination=has("/tmp/x/new.txt")),
                call("run_shell", command=has("mv", "old.txt", "new.txt")))),
    Case("count_py_1", "dev_files", user("how many python files are in /tmp/x/proj?"),
         any_of(call("find_files", directory=has("/tmp/x/proj"), pattern=has(".py")),
                call("run_shell", command=has("/tmp/x/proj", "py")))),
    Case("count_py_2", "dev_files", after("how many python files are in /tmp/x/proj?",
                                          ("find_files", {"directory": "/tmp/x/proj", "pattern": "*.py"},
                                           {"status": "done", "files": [f"/tmp/x/proj/m{i}.py" for i in range(4)]})),
         reply(lambda s: bool(re.search(r"\b(4|four)\b", s)))),
    Case("trash", "dev_files", user("delete the file /tmp/x/trash_me.txt"),
         call("trash_path", path=has("/tmp/x/trash_me.txt"))),
    Case("git_branch", "dev_files", user("what git branch is the repo at /tmp/x/repo on?"),
         call("run_shell", command=has("git"))),
    Case("bg_server", "dev_files", user("start a python http server on port 8765 in /tmp/x in the background"),
         call("start_background", command=has("http.server", "8765"))),
    # honesty
    Case("missing_app", "honesty", after("open the app Flurbnox Studio",
                                         ("open_app", {"name": "Flurbnox Studio"},
                                          {"status": "failed", "error": "No application named 'Flurbnox Studio' is installed"})),
         reply(lambda s: any(n in s for n in NEG))),
    Case("missing_info", "honesty", after("open TextEdit and type the secret code", ("open_app", {"name": "TextEdit"}, DONE)),
         reply(lambda s: "?" in s or "what" in s or "which" in s)),
    Case("chitchat", "honesty", user("hi, how are you?"), reply()),
    Case("unsure_type", "honesty", after("type hello in TextEdit",
                                         ("type_text", {"text": "hello"},
                                          {"status": "unsure", "error": "Typed, but could not read back the text field"})),
         reply(lambda s: bool(re.search(r"not sure|unsure|couldn|could not|can't|cannot|unable|may not|might not|not confirm|verify", s)))),
]


# ---------------------------------------------------------------- runner

def chat(model: str, messages: list[dict], think: bool | None) -> tuple[dict, float]:
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM}] + messages,
            "tools": TOOLS, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 4096}}
    if think is not None:
        body["think"] = think
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    return data, time.perf_counter() - t0


def evaluate(model: str, think: bool | None) -> dict:
    try:
        chat(model, user("hi"), think)  # warm-up: load weights
    except urllib.error.HTTPError as e:
        if think is not None and e.code == 400:
            return evaluate(model, None)  # model doesn't support the think flag
        raise

    rows = []
    for case in CASES:
        try:
            data, secs = chat(model, case.messages, think)
            msg = data.get("message", {})
            calls = msg.get("tool_calls") or []
            if calls:
                fn = calls[0]["function"]
                name, args = fn["name"], fn.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args)
            else:
                name, args = None, {}
            text = msg.get("content", "")
            ok = bool(case.expect(name, args, text))
            err = None
        except Exception as e:  # noqa: BLE001
            name, args, text, ok, secs, err = None, {}, "", False, 0.0, str(e)
        rows.append({"id": case.id, "category": case.category, "ok": ok, "seconds": round(secs, 2),
                     "tool": name, "args": args, "text": text[:300], "error": err})
        print(f"  {'ok ' if ok else 'BAD'} {secs:5.1f}s {case.id:14} -> {name or 'reply'} {json.dumps(args)[:80] if name else repr(text[:80])}",
              flush=True)

    secs = [r["seconds"] for r in rows]
    cats = sorted({r["category"] for r in rows})
    return {
        "model": model, "think": think,
        "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3),
        "by_category": {c: round(sum(r["ok"] for r in rows if r["category"] == c) /
                                 sum(1 for r in rows if r["category"] == c), 2) for c in cats},
        "median_s": round(statistics.median(secs), 2),
        "p90_s": round(sorted(secs)[int(len(secs) * 0.9) - 1], 2),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="comma-separated Ollama model names")
    ap.add_argument("--think", choices=["off", "on", "default"], default="off",
                    help="thinking mode for models that support it (off = fastest)")
    args = ap.parse_args()
    think = {"off": False, "on": True, "default": None}[args.think]

    results = []
    for m in args.models.split(","):
        print(f"\n=== {m} (think={args.think})")
        results.append(evaluate(m, think))

    print("\nmodel                  acc   median  p90   by category")
    for r in results:
        print(f"{r['model']:22} {r['accuracy']:.2f}  {r['median_s']:5.1f}s {r['p90_s']:5.1f}s  {r['by_category']}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"bakeoff-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
