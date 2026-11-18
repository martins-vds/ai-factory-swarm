#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


args = sys.argv[1:]
assert args[:5] == ["api", "--hostname", "github.com", "--method", "GET"], args
assert os.getenv("GH_TOKEN") == "bdd-viewer-credential", "missing runner credentials"
with open(os.environ["DASHBOARD_GH_LOG"], "a") as log:
    log.write(json.dumps({"endpoint": args[5], "method": args[4], "authenticated": True}) + "\n")
fixture = json.loads(Path(os.environ["DASHBOARD_GH_FIXTURE"]).read_text())
url = urlsplit(args[5])
_, owner, repo, *path = url.path.split("/")
assert owner == "martins-vds", args
if repo == fixture.get("denied"):
    sys.exit("gh: Not Found (HTTP 404)")
data = fixture["repos"].get(repo, {})
query = parse_qs(url.query)
state = query.get("state", [None])[0]
pulls = data.get("pulls", [])
issues = data.get("issues", [])

match path:
    case ["actions", "runs"]:
        assert query["status"] == ["action_required"]
        response = {"workflow_runs": data.get("runs", [])}
    case ["pulls"]:
        response = [pr for pr in pulls if pr["state"] == state]
    case ["pulls", number, "files"]:
        response = data.get("files", {}).get(number, [])
    case ["pulls", number]:
        response = next(pr for pr in pulls if pr["number"] == int(number))
    case ["contents", filename]:
        print(data["contents"][f"{query['ref'][0]}:{filename}"])
        sys.exit(0)
    case ["issues"]:
        assert query["assignee"] == ["copilot-swe-agent[bot]"]
        response = [issue for issue in issues if issue["state"] == state]
    case ["issues", number, "timeline"]:
        response = data.get("timeline", {}).get(number, [])
    case ["commits", sha]:
        response = {"commit": {"committer": {"date": data["commits"][sha]}}}
    case _:
        sys.exit(f"Unhandled test REST endpoint: {args[5]}")
print(json.dumps([response] if "--slurp" in args else response))
