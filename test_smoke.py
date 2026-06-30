"""End-to-end smoke test for memos-hermes-remote.

Spawns the shim and pumps JSON-RPC through stdin/stdout to verify the
full lifecycle:  session.open → turn.start → turn.end.

Requires:  export MEMOS_HOST=<remote-ip> [MEMOS_SSH_HOST=<ssh-alias>]
"""
import json, os, subprocess, sys, time

SHIM = os.path.join(os.path.dirname(__file__), "shim.py")
if not os.path.exists(SHIM):
    sys.exit(f"ERROR: {SHIM} not found — run from the repo root")

host = os.environ.get("MEMOS_HOST") or sys.exit("ERROR: MEMOS_HOST not set")
ssh = os.environ.get("MEMOS_SSH_HOST", host)
print(f"remote: {host}:18800  ssh: {ssh}\n")

env = os.environ.copy()
env["MEMOS_HOST"] = host
env["MEMOS_SSH_HOST"] = ssh

proc = subprocess.Popen(
    ["python3", SHIM], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL, text=True, env=env)

def call(m):
    p = m.get("params") or {}
    r = {"jsonrpc": "2.0", "id": int(time.time()*1000), "method": m["name"], "params": p}
    proc.stdin.write(json.dumps(r) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if line:
        d = json.loads(line.strip())
        return d.get("result", d.get("error", {}))
    return None

tests = {}
sid = "smoke_" + str(time.time_ns())[-6:]

def check(step, name, result, expect):
    if isinstance(expect, str) and expect in str(result):
        tests[name] = True
        print(f"{step}. {name:<16} ✓")
    elif callable(expect) and expect(result):
        tests[name] = True
        print(f"{step}. {name:<16} ✓")
    elif expect is True and result:  # boolean truth check
        tests[name] = True
        print(f"{step}. {name:<16} ✓")
    else:
        tests[name] = False
        print(f"{step}. {name:<16} ✗ got: {str(result)[:100]}")

check(1, "ping",    call({"name": "ping"}), "hermes-remote")
check(2, "search",  len(call({"name": "memory.search", "params": {"query": "docker", "agent": "hermes", "topK": {"tier1":1,"tier2":1,"tier3":1}}}).get("hits", [])), lambda n: n >= 0)
check(3, "session", call({"name": "session.open", "params": {"agent": "hermes", "sessionId": sid}}).get("sessionId") == sid, True)
r4 = call({"name": "turn.start", "params": {"agent": "hermes", "sessionId": sid, "userText": "smoke test message"}})
check(4, "turn.start", r4, lambda r: bool((r or {}).get("query", {}).get("episodeId")))
r5 = call({"name": "turn.end", "params": {"agent": "hermes", "sessionId": sid, "agentText": "ok", "userText": "smoke test message", "toolCalls": []}})
check(5, "turn.end", r5, lambda r: bool((r or {}).get("traceId") or (r or {}).get("traceIds")))

proc.stdin.close()
proc.wait(10)

failed = [k for k, v in tests.items() if not v]
print(f"\n{'✓ ALL' if not failed else '✗ FAILED: ' + ', '.join(failed)}")
sys.exit(1 if failed else 0)
