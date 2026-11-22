"""Gateway stubs for afs-spec (ADR-0068): a real local HTTP server at the target's boundary, not a mock of its code.

A spec case's `given.gateways` says how each named gateway answers; the profile's `spec.gateways` says how the
target finds it (an environment variable or a framework setting holding its base URL). For the case, each gateway
gets a server on 127.0.0.1 that answers in order (the last answer repeats) and records every request it gets, so
`then.sent` can say what the target sent. `unreachable: true` points the target at a port nothing listens on.

This file is the harness's: installed with afs-spec and drift-checked like it.
"""
import contextlib
import http.server
import os
import socket
import threading
from unittest import mock


class Stub:
    def __init__(self, answers):
        self.answers = list(answers) or [{"status": 200, "body": ""}]
        self.requests = []
        self._served = 0
        self._server = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self):
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
                stub.requests.append({"method": self.command, "path": self.path, "body": body})
                answer = stub.answers[min(stub._served, len(stub.answers) - 1)]
                stub._served += 1
                payload = str(answer.get("body", "")).encode("utf-8")
                self.send_response(int(answer.get("status", 200)))
                headers = {"Content-Type": "text/plain; charset=utf-8", **(answer.get("headers") or {})}
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _answer

            def log_message(self, *args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()


def unreachable_url():
    """A URL on a port that was free a moment ago: connecting to it is refused."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def answers(spec):
    respond = spec.get("respond")
    if respond is None:
        return []
    return respond if isinstance(respond, list) else [respond]


@contextlib.contextmanager
def gateways(wanted, config, point=None):
    """Start a stub per gateway the case names; yield {name: Stub or None (unreachable)}.

    `config` is the profile's `spec.gateways`. A gateway configured with `env` is pointed at through the environment;
    one with `setting` through `point(setting, url)`, a context manager the stack's adapter provides."""
    stubs = {}
    with contextlib.ExitStack() as stack:
        for name, spec in (wanted or {}).items():
            how = (config or {}).get(name)
            if not how:
                raise ValueError(f"gateway {name!r} isn't in the profile's spec.gateways "
                                 f"(it has: {', '.join(sorted(config or {})) or 'none'})")
            if spec.get("unreachable"):
                stubs[name], url = None, unreachable_url()
            else:
                stub = Stub(answers(spec)).start()
                stack.callback(stub.stop)
                stubs[name], url = stub, stub.url
            if how.get("env"):
                stack.enter_context(mock.patch.dict(os.environ, {how["env"]: url}))
            elif how.get("setting") and point:
                stack.enter_context(point(how["setting"], url))
            else:
                raise ValueError(f"gateway {name!r}: spec.gateways needs `env` or `setting`")
        yield stubs


def sent(stubs):
    return {name: (stub.requests if stub else []) for name, stub in stubs.items()}
