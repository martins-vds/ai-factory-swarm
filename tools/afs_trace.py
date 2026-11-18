"""Every harness tool announces that it ran, and how it ended (ADR-0027).

A tool's entry point is `afs_trace.run(main)`. When the tool ends, one line goes to stderr:

    AFS-TOOL <tool file name> exit=<code>

so CI logs and run journals show, exactly, which harness tools ran and whether they passed. It is
exact where a workflow step only shows that the step ran: a step can call several tools, or call one
only on some branch. `harness_coverage.py` counts these lines; `tests/test_trace.py` fails if an installed
tool skips this. Standard library only.
"""
import os
import sys


def run(main, name=None, verdict=True):
    """`verdict=False` declares a tool that reports and never blocks: harness_coverage.py then needs to
    see it run, not fail (ADR-0027). It changes nothing at run time."""
    name = name or os.path.basename(sys.argv[0])
    try:
        code = main()
    except SystemExit as e:
        code = e.code
    except BaseException:
        _mark(name, 1)
        raise
    if code is not None and not isinstance(code, int):   # sys.exit("message"): print it, as Python would
        print(code, file=sys.stderr)
        code = 1
    code = code or 0
    _mark(name, code)
    sys.exit(code)


def _mark(name, code):
    try:
        print(f"AFS-TOOL {name} exit={code}", file=sys.stderr, flush=True)
    except (OSError, ValueError):       # stderr closed (e.g. a broken pipe): nothing to announce on
        pass
