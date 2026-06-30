#!/usr/bin/env python3
"""memos-hermes-remote: Hermes MemOS provider → remote memos.

Routes JSON-RPC from the memtensor provider to a remote memos server:

  - READ  (search, get_trace, health):  fast HTTP to MEMOS_HOST
  - WRITE (turn.end, capture, …):       SSH stdio to remote bridge.cjs

Provider runs this shim in place of ``node bridge.cjs``.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("MEMOS_DEBUG") else logging.WARNING,
    format="%(asctime)s [shim] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("memos-remote")

# ── config ────────────────────────────────────────────────────
BASE = os.environ.get("MEMOS_REMOTE_URL", "")
if not BASE:
    host = os.environ.get("MEMOS_HOST", "mini2")
    port = os.environ.get("MEMOS_PORT", "18800")
    BASE = "http://{}:{}".format(host, port)

SSH_HOST = os.environ.get("MEMOS_SSH_HOST", os.environ.get("MEMOS_HOST", "mini2"))

READ_TIMEOUT = 90
WRITE_TIMEOUT = 120

# ── version probe ─────────────────────────────────────────────
if "--version" in sys.argv:
    print("v99.99.99 (memos-hermes-remote)")
    sys.exit(0)

# ── HTTP helpers ──────────────────────────────────────────────

def http(path, params=None, body=None, timeout=READ_TIMEOUT):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body else None
    headers = {"Accept": "application/json", "Connection": "close"}
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        return {"_error": str(exc)}

# ── write bridge ──────────────────────────────────────────────
#
# Methods that MUST go through the write bridge because they mutate
# session/episode state on the remote.  Everything else goes HTTP.

LIFECYCLE = frozenset({
    "session.open", "open_session", "openSession",
    "turn.start", "turnStart",
    "turn.end", "turnEnd",
    "capture",
    "sync_turn", "syncTurn",
    "session.close", "closeSession", "close_session",
    "feedback.submit", "feedbackSubmit",
    "close_episode", "closeEpisode",
})

write_proc = None
write_lock = threading.Lock()
write_id = 1000


def bridge():
    global write_proc
    if write_proc and write_proc.poll() is None:
        return write_proc
    log.info("ssh write bridge → %s", SSH_HOST)
    node = os.environ.get("MEMOS_REMOTE_NODE", "node")
    cmd = ["ssh", SSH_HOST,
           "cd $HOME/.hermes/memos-plugin"
           " && exec " + node + " dist/bridge.cjs --agent=hermes --no-viewer"]
    write_proc = subprocess.Popen(
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True,
    )
    time.sleep(3)
    log.info("write bridge pid=%d ready", write_proc.pid)
    return write_proc


def rpc(method, params=None):
    global write_id
    with write_lock:
        b = bridge()
        rid = write_id; write_id += 1
        p = dict(params or {})
        # Default required fields so the remote bridge doesn't crash
        if method in ("turn.end", "turnEnd"):
            p.setdefault("toolCalls", [])
        if method in ("feedback.submit", "feedbackSubmit"):
            p.setdefault("polarity", "neutral")
        payload = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": p},
                             ensure_ascii=False)
        log.debug("write rpc id=%d %s", rid, method)
        b.stdin.write(payload + "\n")
        b.stdin.flush()

        deadline = time.time() + WRITE_TIMEOUT
        while time.time() < deadline:
            line = b.stdout.readline()
            if not line:
                raise Exception("write bridge closed")
            try:
                msg = json.loads(line.strip())
                if msg.get("id") == rid:
                    return msg.get("error") and {"error": msg["error"]} or msg.get("result", {})
            except json.JSONDecodeError:
                continue
        raise Exception("write rpc timeout: " + method)


# ── main loop ─────────────────────────────────────────────────

log.info("ready base=%s ssh=%s", BASE, SSH_HOST)

for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        req = json.loads(raw)
    except json.JSONDecodeError:
        continue

    method = req.get("method", "")
    params = req.get("params", {})
    if not isinstance(params, dict):
        params = {}
    rid = req.get("id")

    result = None
    try:
        # ── read ──
        if method == "ping":
            result = {"ok": True, "shim": "memos-hermes-remote"}

        elif method in ("health", "core.health"):
            result = http("/api/v1/health")

        elif method in ("search", "memory.search"):
            q = params.get("query", "")
            top = 3
            if isinstance(params.get("topK"), dict):
                tk = params["topK"]
                top = max(tk.get("tier1", 3), tk.get("tier2", 3), tk.get("tier3", 3))
            elif isinstance(params.get("topK"), (int, float)):
                top = int(params["topK"])
            result = http("/api/v1/memory/search",
                          {"q": q, "top": top, "agent": params.get("agent", "hermes"),
                           "sessionId": params.get("sessionId", "")})

        # ── lifecycle (write bridge) ──
        elif method in LIFECYCLE:
            result = rpc(method, params)

        elif method == "get_trace":
            result = http("/api/v1/traces/" + params.get("traceId", ""))

        # ── unsupported ──
        elif method == "host.llm.complete":
            result = {"error": "host_llm_disabled"}

        # ── unknown: try write bridge ──
        else:
            log.debug("method '%s' → write bridge", method)
            result = rpc(method, params)

        if result is None:
            result = {"ok": True}

    except Exception as exc:
        log.error("%s: %s", method, exc)
        result = {"error": {"code": -1, "message": str(exc)}}

    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result},
                                 ensure_ascii=False) + "\n")
    sys.stdout.flush()
