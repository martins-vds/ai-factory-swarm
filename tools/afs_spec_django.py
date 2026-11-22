"""The Django adapter for afs-spec (ADR-0061): run spec cases through the test client and management commands.

Each case runs in its own transaction on the test database, rolled back afterwards, as Django's TestCase
does. Setup goes through public side channels only: fixtures (`loaddata`) and management commands. The one
thing it may set directly is the clock, a boundary: `given.clock` fixes `django.utils.timezone.now` and
`localdate` for the case.

Settings come from `DJANGO_SETTINGS_MODULE`, else pytest's `DJANGO_SETTINGS_MODULE` in pyproject.toml; its
`pythonpath` entries go on sys.path, as pytest-django would put them.
"""
import contextlib
import datetime as dt
import io
import json
import os
import pathlib
import sys
from unittest import mock

try:
    import tomllib
except ImportError:                                    # Python < 3.11
    tomllib = None


def pytest_settings(root="."):
    path = pathlib.Path(root) / "pyproject.toml"
    if tomllib is None or not path.exists():
        return None, []
    conf = tomllib.loads(path.read_text(encoding="utf-8")).get("tool", {}).get("pytest", {}).get("ini_options", {})
    paths = conf.get("pythonpath") or []
    return conf.get("DJANGO_SETTINGS_MODULE"), [paths] if isinstance(paths, str) else list(paths)


def parse_clock(value):
    value = str(value).replace(" ", "T")
    moment = dt.datetime.fromisoformat(value if "T" in value else value + "T12:00:00")
    return moment


class DjangoAdapter:
    def __init__(self, root="."):
        self.root = pathlib.Path(root).resolve()
        self._old_db = None

    def setup(self):
        settings_module, paths = pytest_settings(self.root)
        for p in reversed(paths):
            sys.path.insert(0, str(self.root / p))
        sys.path.insert(0, str(self.root))
        if settings_module:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
        if not os.environ.get("DJANGO_SETTINGS_MODULE"):
            raise RuntimeError("afs-spec: set DJANGO_SETTINGS_MODULE, or DJANGO_SETTINGS_MODULE under "
                               "[tool.pytest.ini_options] in pyproject.toml")
        import django
        django.setup()
        from django.conf import settings
        from django.db import connection
        from django.test.utils import setup_test_environment
        setup_test_environment()
        if "testserver" not in settings.ALLOWED_HOSTS and "*" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
        self._old_db = connection.creation.create_test_db(verbosity=0, autoclobber=True, keepdb=False)

    def teardown(self):
        from django.db import connection
        from django.test.utils import teardown_test_environment
        if self._old_db is not None:
            connection.creation.destroy_test_db(self._old_db, verbosity=0)
        teardown_test_environment()

    @contextlib.contextmanager
    def case(self, given):
        from django.core.management import call_command
        from django.db import transaction
        with contextlib.ExitStack() as stack:
            if given.get("clock"):
                moment = parse_clock(given["clock"])
                from django.conf import settings
                from django.utils import timezone
                aware = timezone.make_aware(moment) if settings.USE_TZ else moment
                stack.enter_context(mock.patch("django.utils.timezone.now", lambda: aware))
                stack.enter_context(mock.patch("django.utils.timezone.localdate",
                                               lambda value=None, timezone=None: moment.date()))
            stack.enter_context(transaction.atomic())
            try:
                for fixture in given.get("fixtures") or []:
                    call_command("loaddata", fixture, verbosity=0)
                for cmd in given.get("commands") or []:
                    call_command(cmd["name"], *[str(a) for a in cmd.get("args") or []], stdout=io.StringIO())
                yield
            finally:
                transaction.set_rollback(True)

    def act(self, when):
        if "http" in when:
            return self._http(when["http"])
        return self._command(when["command"])

    def _http(self, h):
        from django.test import Client
        client = Client(raise_request_exception=False)
        headers = dict(h.get("headers") or {})
        if h.get("htmx"):
            headers["HX-Request"] = "true"
        extra = {"HTTP_" + k.upper().replace("-", "_"): v for k, v in headers.items()}
        method = h["method"].lower()
        if "json" in h:
            resp = client.generic(h["method"], h["path"], json.dumps(h["json"]), content_type="application/json", **extra)
        elif method == "get":
            resp = client.get(h["path"], h.get("form") or {}, **extra)
        else:
            resp = getattr(client, method)(h["path"], h.get("form") or {}, **extra)
        text = resp.content.decode("utf-8", errors="replace") if hasattr(resp, "content") else ""
        body = None
        if "json" in (resp.get("Content-Type") or ""):
            try:
                body = json.loads(text)
            except ValueError:
                body = None
        return {"status": resp.status_code, "text": text, "json": body,
                "headers": {k.lower(): v for k, v in resp.items()}}

    def _command(self, c):
        from django.core.management import call_command
        out = io.StringIO()
        try:
            call_command(c["name"], *[str(a) for a in c.get("args") or []], stdout=out, stderr=out)
            status = 0
        except SystemExit as e:
            status = e.code if isinstance(e.code, int) else 1
        except Exception as e:                         # a command that raises answers with status 1 and its message
            out.write(f"{type(e).__name__}: {e}")
            status = 1
        return {"status": status, "text": out.getvalue(), "json": None, "headers": {}}
