# memos-hermes-remote

Remote bridge for [@memtensor/memos-local-plugin](https://github.com/MemTensor/MemOS) —
connects a Hermes Agent running on one machine to a MemOS instance on another.

    Hermes (MacBook)              Tailscale            Remote
    ┌─────────────────┐         <remote-ip>          ┌──────────────────────┐
    │ memtensor        │  HTTP ──────────▶ :18800     │ memos daemon (http)  │
    │   shim.py        │  SSH  ──────────▶ bridge.cjs │ memos.db             │
    │                  │                              │ bge-m3 embeddings    │
    └─────────────────┘                              └──────────────────────┘

- **Reads** (search / get_trace / health) → fast HTTP to the remote viewer daemon
- **Writes** (turn.end / session.open / …) → SSH stdio to remote `bridge.cjs`


## Install

### 1. Set up the remote

The remote host needs a working MemOS daemon and SSH access:

```bash
# on remote: install node ≥20, start the daemon
node --version                         # ≥20
cd ~/.hermes/memos-plugin
node dist/bridge.cjs --agent=hermes --daemon  # leave running, or use launchd
```

Verify it's reachable:

```bash
curl http://<remote-ip>:18800/api/v1/ping
# → {"ok":true,"service":"memos-local-plugin",…}
```

### 2. Install the shim

```bash
git clone https://github.com/xuyangbo/memos-hermes-remote.git
cd memos-hermes-remote
chmod +x install.sh shim.py
./install.sh
```

`install.sh` writes `shim.py` into `~/.hermes/memos-plugin/` and links the
provider so Hermes can discover it.

### 3. Configure the provider

Two changes to `~/.hermes/config.yaml`:

```yaml
# 1. Enable the provider
memory:
  provider: memtensor

# 2. Write .memos-node-bin to point at the shim
# (install.sh does this automatically)

# Or manually:
echo "/path/to/shim.py" > ~/.hermes/memos-plugin/.memos-node-bin
```

### 4. Set environment variables

```bash
export MEMOS_HOST=<your-remote-ip>     # hostname or IP of the remote daemon
export MEMOS_SSH_HOST=<your-ssh-alias>  # SSH config alias (or same as MEMOS_HOST)
export MEMOS_REMOTE_NODE=node           # node binary on remote (if not on default PATH)
```

Restart Hermes after these changes.


## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMOS_HOST` | `—` | Hostname/IP for HTTP read operations (required) |
| `MEMOS_PORT` | `18800` | Port for HTTP |
| `MEMOS_REMOTE_URL` | `—` | Full base URL (overrides host+port) |
| `MEMOS_SSH_HOST` | (same as MEMOS_HOST) | SSH target for write bridge |
| `MEMOS_REMOTE_NODE` | `$HOME/.local/node/bin/node` | Path to node on the remote |
| `MEMOS_DEBUG` | unset | Set to `1` for verbose logging |


## How it works

Hermes' memtensor provider spawns a "Node.js bridge" by reading `.memos-node-bin`.
The shim pretends to be that bridge:

1. Provider calls `session.open` / `turn.start` / `turn.end` via JSON-RPC on stdin
2. Shim routes lifecycle methods through SSH to remote `bridge.cjs`
3. Shim routes read methods (search, health, get_trace) via HTTP to the viewer daemon
4. JSON-RPC responses are written to stdout exactly as the provider expects

No code changes to the provider, bridge, or Hermes core.


## Limitations

- **No LLM fallback.**  `host.llm.complete` is disabled.  The remote must use a direct
  LLM provider; host-side LLM cascading is not proxied.
- **One write session at a time.**  The SSH bridge is single-threaded.  Concurrent
  Hermes conversations share one write pipe.
- **SSH latency.**  First write in a session takes 3–5 seconds (bridge cold start).
  Subsequent writes in the same session are 1–2 seconds.
- **SSH config aliases.**  `MEMOS_HOST` must be a resolvable hostname or IP.
  Use `MEMOS_SSH_HOST` for SSH config aliases that aren't DNS-resolvable.
- **Node ≥20 required on remote.**  `better-sqlite3` native addon requires it.


## License

MIT
