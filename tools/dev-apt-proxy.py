#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Minimal HTTP forward proxy bound to the NCM host end, so the tablet can
run apt natively (chroot, no QEMU) without giving the host NAT/root or the
device a default route. apt handles plain-HTTP archive URLs through a proxy
via absolute-URI GET; CONNECT (https) is answered 501 to fail fast.

Usage: dev-apt-proxy.py [bind-addr] [port]   (default 192.168.77.10:8080)
"""
import socket
import socketserver
import sys
import threading
import urllib.request

BIND = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"  # wildcard: the NCM
# host address only exists while the tablet's gadget link is up; a wildcard
# listener survives link loss and accepts again on the next session.
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8080


class Proxy(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self._handle()
        except Exception as exc:  # keep the daemon alive on per-request errors
            print(f"[proxy] {exc}", file=sys.stderr)

    def _handle(self):
        conn = self.request
        conn.settimeout(60)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return
            data += chunk
            if len(data) > 65536:
                return
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode(errors="replace").split("\r\n")
        method, url = lines[0].split(" ")[:2]
        if method == "CONNECT":
            conn.sendall(b"HTTP/1.1 501 https not proxied\r\n\r\n")
            return
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        headers["Connection"] = "close"
        headers.pop("Proxy-Connection", None)
        # apt's differential Range requests 416 against by-hash files whose
        # state shifted under us; full-file answers are always acceptable.
        headers.pop("Range", None)
        headers.pop("If-Range", None)
        if method == "GET":
            body = None
        else:  # POST etc.: content-length framed body already (partially) read
            length = int(headers.get("Content-Length", "0"))
            body = rest
            while len(body) < length:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                body += chunk
        req = urllib.request.Request(url, data=body, method=method)
        for k, v in headers.items():
            if k.lower() not in ("host", "content-length"):
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=120) as resp:
            out = [f"HTTP/1.1 {resp.status} {resp.reason}"]
            for k, v in resp.headers.items():
                if k.lower() in ("transfer-encoding", "connection"):
                    continue
                out.append(f"{k}: {v}")
            payload = resp.read()
            out.append(f"Content-Length: {len(payload)}")
            conn.sendall(("\r\n".join(out) + "\r\n\r\n").encode() + payload)


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64  # apt opens many parallel fetches


if __name__ == "__main__":
    Server.allow_reuse_address = True
    with Server((BIND, PORT), Proxy) as srv:
        print(f"[proxy] apt forward proxy on {BIND}:{PORT}", file=sys.stderr)
        srv.serve_forever()
