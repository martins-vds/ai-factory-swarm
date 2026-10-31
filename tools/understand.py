#!/usr/bin/env python3
"""Build the source graphs with Understand Anything through the GitHub Copilot SDK (Phase 2, ADR-0009).

Runs `/understand`, then `/understand-domain`, non-interactively on --dir (a git repo: the source at its
pinned SHA, or a slice extracted from it), with the pinned and patched plugin from --plugin. Copies the
resulting graphs to --out with a run summary:

  knowledge-graph.json, domain-graph.json   Understand Anything's output, unchanged
  run.md                                    per step: seconds, model calls, tokens, tool calls, errors
  events-<step>.jsonl                       every session event, short payloads (debugging; gitignore it)

Auth: the token in the environment variable --token-env (default GITHUB_TOKEN: the Actions token with
`copilot-requests: write`; spike M1-1). Exit 1 if knowledge-graph.json was not produced.
Needs: pip `github-copilot-sdk` and the Copilot CLI runtime (`python -m copilot download-runtime`).
"""
import argparse
import asyncio
import collections
import json
import os
import pathlib
import shutil
import sys
import time
import traceback

STEPS = [
    ("understand", "Use the `understand` skill to analyze the current directory and build its knowledge "
                   "graph. Follow the skill's instructions exactly. Do not ask questions; this is a "
                   "non-interactive run, so choose the default whenever the skill offers a choice."),
    ("understand-domain", "Use the `understand-domain` skill on the current directory to extract business "
                          "domains, flows and steps, reusing the existing knowledge graph. Do not ask "
                          "questions; choose the default whenever offered a choice."),
]
GRAPHS = ("knowledge-graph.json", "domain-graph.json")
GRAPH_DIRS = (".understand-anything", ".ua")


def short(obj, limit=400):
    try:
        s = json.dumps(obj, default=lambda o: getattr(o, "__dict__", str(o)))
    except Exception:
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + "…"


async def run_step(client, name, prompt, a, out, lines):
    from copilot.session import PermissionHandler
    counts, tools, tok = collections.Counter(), collections.Counter(), collections.Counter()
    start = time.time()
    with open(out / f"events-{name}.jsonl", "w", encoding="utf-8") as log:
        def on_event(event):
            data = getattr(event, "data", None)
            kind = type(data).__name__
            counts[kind] += 1
            if kind == "ToolExecutionStartData":
                tools[str(getattr(data, "tool_name", None) or getattr(data, "name", "?"))] += 1
            elif kind == "AssistantUsageData":
                tok["calls"] += 1
                for k in ("input_tokens", "output_tokens", "cache_read_tokens"):
                    tok[k] += getattr(data, k, None) or 0
            log.write(json.dumps({"t": round(time.time() - start, 2), "type": kind, "data": short(data)}) + "\n")

        session = await client.create_session(
            on_permission_request=PermissionHandler.approve_all, working_directory=str(a.dir),
            skill_directories=[str(a.plugin / "understand-anything-plugin/skills")],
            enable_config_discovery=True, **({"model": a.model} if a.model else {}))
        session.on(on_event)
        error = None
        try:
            await session.send_and_wait(prompt, timeout=a.timeout)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            (out / f"error-{name}.txt").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            try:
                await session.disconnect()
            except Exception:
                pass
    lines += [f"## {name}", "",
              f"- Seconds: {round(time.time() - start)}", f"- Error: {error or 'none'}",
              f"- Model calls: {tok['calls']}; tokens in {tok['input_tokens']:,}, out {tok['output_tokens']:,}, "
              f"cache read {tok['cache_read_tokens']:,}",
              "- Tool calls: " + (", ".join(f"{k} {v}" for k, v in tools.most_common(12)) or "none"), ""]
    return error


async def run(a):
    from copilot import CopilotClient
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = ["# Understand Anything run", "",
             f"- Directory: `{a.dir}`", f"- Plugin: `{a.plugin}`", f"- Model: {a.model or 'default'}", ""]
    async with CopilotClient(github_token=os.environ.get(a.token_env),
                             builtin_plugin_directories=(str(a.plugin),)) as client:
        for name, prompt in STEPS:
            await run_step(client, name, prompt, a, out, lines)
    found = []
    for g in GRAPHS:
        for d in GRAPH_DIRS:
            if (a.dir / d / g).exists():
                shutil.copyfile(a.dir / d / g, out / g)
                found.append(g)
                break
    lines.append("Graphs: " + (", ".join(found) or "none produced"))
    (out / "run.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if "knowledge-graph.json" in found else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, type=pathlib.Path, help="folder to analyze (a git repo)")
    ap.add_argument("--plugin", required=True, type=pathlib.Path, help="Understand Anything checkout (patched)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("AFS_GRAPH_MODEL") or None)
    ap.add_argument("--timeout", type=float, default=5400)
    ap.add_argument("--token-env", default="GITHUB_TOKEN")
    a = ap.parse_args()
    try:
        return asyncio.run(run(a))
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
