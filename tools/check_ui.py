#!/usr/bin/env python3
"""UI checks a tool can make every time (phase 3e): htmx error responses render, and a committed pre-built
stylesheet holds every utility class the templates use.

Configured in the profile, under `ui_checks:` (schemas/profile.schema.json):

    ui_checks:
      templates: ["templates/**/*.html", "src/**/templates/**/*.html"]
      scripts: ["static/**/*.js"]        # optional: where htmx configuration may also live
      htmx_errors: true                  # pages that send htmx requests must render error responses
      built_css: static/css/tailwind.css # optional: a committed, pre-built Tailwind stylesheet

Both checks look at the templates this branch changed (against `--changed-since`, else $AFS_BASE, origin/main,
main), so a defect from an earlier ticket doesn't fail later work. `--all` checks every template.

- **htmx_errors.** htmx (1.x and 2.x) swaps no 4xx or 5xx response by default, so an error fragment a view
  returns never appears. A changed template that sends an htmx request (`hx-get`, `hx-post`, `hx-put`,
  `hx-patch`, `hx-delete`) fails unless the templates or scripts handle error responses somewhere:
  - `htmx.config.responseHandling` (htmx 2), set by script or in an `htmx-config` meta tag;
  - an `htmx:beforeSwap` or `htmx:responseError` listener;
  - or the response-targets extension (`hx-target-error`, `hx-target-4*`, `hx-target-5*`).

  Eval v3e to v3g: LL-03's payment failure and BK-05G's unknown-cargo dialogs both returned error fragments
  that never showed, and Verifiers found them in one run of three.
- **built_css.** When the stylesheet is committed pre-built, a template can use a utility the build never saw.
  The browser then ignores it. Every Tailwind utility a changed template uses must have its selector in the
  stylesheet; rebuild the stylesheet in the same change. Eval v3g: LL-04's About page used `py-8`, `mt-8` and
  `leading-relaxed`, which the LL-01 build lacks. Only Tailwind utility shapes are checked (spacing, sizing,
  type, color, layout, with variants and arbitrary values), so component classes (daisyUI's `card`, `btn`)
  and the target's own classes are left alone.

Usage: check_ui.py [--root <repo>] [--profile <path>] [--changed-since REF | --all]
Runs in the idiom gate. Exits 1 on a finding, 2 on a bad configuration; with no `ui_checks:`, it passes.
"""
import argparse
import os
import pathlib
import re
import subprocess
import sys

import yaml

HX_REQUEST = re.compile(r"\bhx-(get|post|put|patch|delete)\s*=", re.I)
HX_ERROR_HANDLING = re.compile(
    r"responseHandling|htmx:beforeSwap|htmx:responseError|hx-on:{1,2}(htmx:)?(before-swap|response-error)"
    r"|hx-target-(error|[45])", re.I)
# A script that edits htmx 2's default rules by matching their `code` strings. htmx 2 ships exactly these codes;
# a match on any other string (e.g. '4..', the regex for 4xx, isn't how the default is spelled) changes nothing.
HX_DEFAULT_CODES = {"204", "[23]..", "[45]..", "..."}
HX_CODE_MATCH = re.compile(r"""\.code\s*(?:===?|!==?)\s*(["'])([^"']*)\1|(["'])([^"']*)\3\s*(?:===?|!==?)\s*\w+\.code\b""")
CLASS_ATTR = re.compile(r"""\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
DJANGO_TAG = re.compile(r"{%.*?%}|{{.*?}}|{#.*?#}", re.S)

# Tailwind utility shapes: a known prefix, then a value (scale, fraction, color or [arbitrary]).
PREFIXES = (
    "p px py pt pr pb pl ps pe m mx my mt mr mb ml ms me space-x space-y gap gap-x gap-y "
    "w min-w max-w h min-h max-h size basis grow shrink order inset inset-x inset-y top right bottom left start "
    "end z text font leading tracking indent bg from via to border border-x border-y border-t border-r border-b "
    "border-l rounded rounded-t rounded-r rounded-b rounded-l rounded-tl rounded-tr rounded-bl rounded-br shadow "
    "ring ring-offset outline outline-offset opacity grid-cols grid-rows col-span col-start col-end row-span "
    "row-start row-end items justify content self place-items place-content place-self overflow overflow-x "
    "overflow-y whitespace break decoration underline-offset list object aspect cursor select transition "
    "duration ease delay scale rotate translate-x translate-y skew-x skew-y origin fill stroke divide-x divide-y "
    "divide line-clamp columns align"
).split()
KEYWORDS = set((
    "block inline inline-block inline-flex inline-grid flex grid hidden contents table table-row table-cell "
    "static fixed absolute relative sticky underline overline line-through no-underline uppercase lowercase "
    "capitalize normal-case italic not-italic truncate container sr-only not-sr-only shadow rounded border grow "
    "shrink flex-row flex-col flex-wrap flex-nowrap flex-1 flex-auto flex-none antialiased visible invisible "
    "isolate transform transition ring outline-none"
).split())
COLORS = ("slate gray zinc neutral stone red orange amber yellow lime green emerald teal cyan sky blue indigo violet "
          "purple fuchsia pink rose").split()
WORDS = ("auto full screen svh dvh min max fit px none xs sm base md lg xl [2-9]xl tight snug normal relaxed loose "
         "wide wider widest tighter thin extralight light medium semibold bold extrabold black white transparent "
         "current inherit left center right justify start end between around evenly stretch baseline col row "
         "col-reverse row-reverse wrap nowrap hidden visible scroll clip x y t b l r tl tr bl br sans serif mono "
         "square video cover contain pointer default not-allowed disc decimal inside outside break-words "
         "break-all pre pre-line pre-wrap ellipsis linear in out in-out top bottom middle").split()
VALUE = (r"(\[[^\]\s]+\]"                                            # arbitrary: [#66705b], [.2em]
         r"|-?[0-9][0-9.]*(\/[0-9]+)?"                                  # scale or fraction: 8, 0.5, 1/2
         r"|(" + "|".join(COLORS) + r")-[0-9]{2,3}(\/[0-9]+)?"           # palette color: slate-50, red-500/50
         r"|(" + "|".join(WORDS) + r")(\/[0-9]+)?)")
UTILITY = re.compile(r"^(!?)(-?)(" + "|".join(sorted(map(re.escape, PREFIXES), key=len, reverse=True))
                     + r")(-" + VALUE + r")?$")


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def changed_since(root, since):
    """(ref, changed paths) against the first base ref that exists, or (None, None) when none does."""
    for ref in ([since] if since else []) + [os.environ.get("AFS_BASE", ""), "origin/main", "main"]:
        if not ref:
            continue
        r = git(root, "diff", "--name-only", "--diff-filter=AM", f"{ref}...HEAD")
        if r.returncode == 0:
            untracked = git(root, "ls-files", "--others", "--exclude-standard").stdout.split()
            return ref, set(r.stdout.split()) | set(untracked)
    return None, None


def glob_regex(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def files(root, globs):
    regs = [glob_regex(g) for g in globs]
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not rel.startswith((".git/", ".migration/", "node_modules/", ".venv/")) \
                and any(r.match(rel) for r in regs):
            out.append(rel)
    return out


def is_utility(token):
    base = token.rsplit(":", 1)[-1]          # strip variants: md:, hover:, dark:md:
    return base.lstrip("!-") in KEYWORDS or bool(UTILITY.match(base))


def css_escape(token):
    """The selector Tailwind writes for a class: every character outside [A-Za-z0-9_-] is backslash-escaped,
    and a leading digit becomes a hex escape."""
    out = []
    for i, ch in enumerate(token):
        if i == 0 and ch.isdigit():
            out.append(f"\\3{ch} ")
        elif re.match(r"[A-Za-z0-9_-]", ch):
            out.append(ch)
        else:
            out.append("\\" + ch)
    return "." + "".join(out)


def class_tokens(text):
    """[(line, token)] for every class in a template's class attributes, Django tags removed."""
    out = []
    for m in CLASS_ATTR.finditer(text):
        value = DJANGO_TAG.sub(" ", m.group(1) if m.group(1) is not None else m.group(2))
        line = text.count("\n", 0, m.start()) + 1
        out += [(line, t) for t in value.split() if t and not re.search(r"[{}%]", t)]
    return out


def unknown_codes(text):
    """[(line, code)] for each comparison against a `code` htmx 2's default response rules don't have."""
    out = []
    for m in HX_CODE_MATCH.finditer(text):
        code = m.group(2) if m.group(2) is not None else m.group(4)
        if code not in HX_DEFAULT_CODES:
            out.append((text.count("\n", 0, m.start()) + 1, code))
    return out


def htmx_findings(root, templates, scripts, targets):
    found, handled = [], False
    for f in templates + scripts:
        text = (root / f).read_text(encoding="utf-8", errors="ignore")
        if not HX_ERROR_HANDLING.search(text):
            continue
        bad = unknown_codes(text) if "responseHandling" in text else []
        for line, code in bad:
            found.append((f, line, f"edits htmx's response rules by matching `code` '{code}', but htmx 2's default "
                          f"rules are {', '.join(sorted(HX_DEFAULT_CODES))}: nothing matches, so error responses "
                          "still aren't swapped. Match '[45]..', or assign a whole `htmx.config.responseHandling`"))
        handled = handled or not bad
    if handled:
        return found
    for rel in targets:
        text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        for m in HX_REQUEST.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            found.append((rel, line, f"sends an htmx request (`hx-{m.group(1).lower()}`), but nothing handles error "
                          "responses: htmx swaps no 4xx or 5xx response by default, so an error fragment never "
                          "shows. Set `htmx.config.responseHandling` (htmx 2), add an `htmx:beforeSwap` listener, "
                          "or use the response-targets extension"))
            break                                   # one finding per template is enough
    return found


def css_findings(root, css_path, targets):
    css_file = root / css_path
    if not targets:
        return []
    if not css_file.exists():
        return [(css_path, 0, "`ui_checks.built_css` names a stylesheet that doesn't exist")]
    css = css_file.read_text(encoding="utf-8", errors="ignore")
    found = []
    for rel in targets:
        missing = {}
        for line, token in class_tokens((root / rel).read_text(encoding="utf-8", errors="ignore")):
            if is_utility(token) and css_escape(token) not in css and token not in missing:
                missing[token] = line
        for token, line in missing.items():
            found.append((rel, line, f"uses `{token}`, which {css_path} doesn't contain: the browser ignores it. "
                          "Rebuild the stylesheet in this change"))
    return found


def config_errors(cfg):
    if not isinstance(cfg, dict) or not cfg.get("templates"):
        return ["`ui_checks` needs `templates` (path globs), and `htmx_errors: true` or `built_css`"]
    if not cfg.get("htmx_errors") and not cfg.get("built_css"):
        return ["`ui_checks` turns on no check: set `htmx_errors: true`, `built_css`, or both"]
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--profile", default=None, help="default: <root>/.migration/profile.yaml")
    ap.add_argument("--changed-since", default=None)
    ap.add_argument("--all", action="store_true", help="check every template, not only the changed ones")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root).resolve()
    profile = pathlib.Path(a.profile) if a.profile else root / ".migration/profile.yaml"
    doc = (yaml.safe_load(profile.read_text(encoding="utf-8")) or {}) if profile.exists() else {}
    cfg = doc.get("ui_checks")
    if cfg is None:
        print("AFS-RESULT gate=ui checks=0 findings=0 (the profile has no `ui_checks`)")
        return 0
    errs = config_errors(cfg)
    if errs:
        print("\n".join(errs))
        print("AFS-RESULT gate=ui error=bad-config")
        return 2
    templates = files(root, cfg["templates"])
    scripts = files(root, cfg.get("scripts") or [])
    if a.all:
        targets, scope = templates, "every template"
    else:
        ref, changed = changed_since(root, a.changed_since)
        if changed is None:
            targets, scope = templates, "every template (no base ref found)"
        else:
            targets, scope = [t for t in templates if t in changed], f"templates changed since {ref}"
    found = []
    if cfg.get("htmx_errors"):
        found += htmx_findings(root, templates, scripts, targets)
    if cfg.get("built_css"):
        found += css_findings(root, cfg["built_css"], targets)
    for rel, line, msg in found:
        print(f"{rel}:{line}: {msg}")
    print(f"AFS-RESULT gate=ui scope=\"{scope}\" templates={len(targets)} findings={len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import afs_trace
    afs_trace.run(main)
