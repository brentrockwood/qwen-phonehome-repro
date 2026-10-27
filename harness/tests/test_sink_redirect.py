#!/usr/bin/env python3
"""Behavioural test that sink replay does NOT follow a redirect (review 3).

Stands up two loopback HTTP servers: a redirector that 302s to a second
"target" endpoint, and the target itself. We point sink_client.replay at the
redirector and assert the target received zero requests — i.e. the redirect was
not followed, so no request could be bounced to another host. No external
traffic; both servers are on 127.0.0.1.
Run: python harness/tests/test_sink_redirect.py
"""
import os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sink_client  # noqa: E402

TARGET_HITS = []


def make_server(handler_cls):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def main():
    # target: records any request it receives (it must receive none)
    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            TARGET_HITS.append(self.path)
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a):
            pass

    target_srv, target_port = make_server(Target)

    # redirector: 302 -> the target
    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target_port}/leaked")
            self.end_headers()
        def log_message(self, *a):
            pass

    redir_srv, redir_port = make_server(Redirector)

    sink = f"http://127.0.0.1:{redir_port}"
    status = sink_client.replay(sink, "http://x.oss-cn-hangzhou.aliyuncs.com/p", {})

    target_srv.shutdown(); redir_srv.shutdown()

    # The safety property: the target endpoint was never contacted.
    ok_no_follow = (len(TARGET_HITS) == 0)
    # replay must return a status string (not raise); the 302 may surface either
    # as "recorded 302" or as a handled capture-error — both mean "not followed".
    ok_status = isinstance(status, str) and "302" in status
    print(f"{'PASS' if ok_no_follow else 'FAIL'}: redirect not followed "
          f"(target hits={len(TARGET_HITS)})")
    print(f"{'PASS' if ok_status else 'FAIL'}: replay handled the 302 without "
          f"following it and returned a status (status={status!r})")
    sys.exit(0 if (ok_no_follow and ok_status) else 1)


if __name__ == "__main__":
    main()
