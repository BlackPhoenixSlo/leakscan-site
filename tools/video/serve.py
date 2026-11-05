"""Local static server for site/ with HTTP Range support (python's http.server has none, so <video> can't seek).
Used by cue_shots.py:  with serve(SITE) as base: ...  (base = "http://127.0.0.1:<port>/")."""
import contextlib, functools, http.server, os, re, threading

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "site")


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng or "")
        if not m or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        a, b = m.groups()
        start, end = (int(a), int(b or size - 1)) if a else (max(0, size - int(b)), size - 1)
        if start >= size:
            self.send_error(416)
            return None
        end = min(end, size - 1)
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._left = end - start + 1
        return f

    def copyfile(self, src, dst):
        left = getattr(self, "_left", None)
        if left is None:
            return super().copyfile(src, dst)
        while left > 0:
            buf = src.read(min(65536, left))
            if not buf:
                break
            dst.write(buf)
            left -= len(buf)


@contextlib.contextmanager
def serve(directory=SITE):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RangeHandler, directory=os.path.abspath(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()
