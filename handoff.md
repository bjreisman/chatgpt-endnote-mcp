# Handoff

## Repo / Branch

- Repo: `bjreisman/chatgpt-endnote-mcp`
- Local path: `/Users/breisma1/Projects/endnote-mcp`
- Working branch: `codex/chatgpt-bridge-foundation`

## What this fork is trying to do

This repo is a fork of `gokmengokhan/endnote-mcp` and is an active attempt to port the project toward ChatGPT-compatible workflows.

There are now three relevant usage modes in the fork:

1. Preserved local MCP baseline from the original project
2. Local web app backed by the OpenAI API (`serve-app`)
3. Tunnel-backed local MCP server meant for ChatGPT Developer Mode (`serve-chatgpt-local`)

There is also a small hardening pass on top of those experiments:

- `serve-app` now refuses non-loopback binds unless you pass `--allow-public`
- `serve-companion` now requires `--allow-public` plus a bearer token before it will bind beyond localhost
- companion `/health` no longer leaks local file paths and requires auth whenever a companion token is configured

## What is already implemented

### 1. Shared EndNote runtime

- `src/endnote_mcp/tool_runtime.py`
- Shared logic for:
  - reference search
  - full-text PDF search
  - semantic search
  - metadata lookup
  - citations / bibliographies / BibTeX
  - PDF page reads

This keeps the original EndNote core reusable across multiple frontends.

### 2. Preserved local MCP server

- `src/endnote_mcp/server.py`
- Still works as the direct local MCP baseline.

### 3. Bridge foundation

- `src/endnote_mcp/companion.py`
- `src/endnote_mcp/gateway.py`
- `src/endnote_mcp/bridge_client.py`
- `src/endnote_mcp/bridge_models.py`

This was built as an early remote-gateway / local-companion architecture for a future ChatGPT path.

### 4. Local web app

- `src/endnote_mcp/chat_app.py`
- CLI entrypoint: `endnote-mcp serve-app`

This gives a local “ChatGPT-like” interface that:
- keeps EndNote search and PDF access local
- uses the OpenAI Responses API for the chat layer
- is the least painful working user experience right now

### 5. Tunnel-backed local MCP server for ChatGPT

- `src/endnote_mcp/chatgpt_local_server.py`
- CLI entrypoint: `endnote-mcp serve-chatgpt-local`

This was built for:
- local MCP server on `127.0.0.1:8787`
- `streamable-http` transport via FastMCP
- read/fetch-oriented tool set only
- bearer-token auth
- tunnel exposure via `ngrok` or `localtunnel`

### 6. Tests

Added tests for the new code:

- `tests/test_bridge.py`
- `tests/test_chat_app.py`
- `tests/test_chatgpt_local_server.py`

Last successful full run during this session:

- `106 passed`

## Current working-tree state

There are local uncommitted changes at the time of this handoff.

Expected files involved:

- modified:
  - `README.md`
  - `src/endnote_mcp/cli.py`
  - `src/endnote_mcp/config.py`
- untracked/new:
  - `src/endnote_mcp/chatgpt_local_server.py`
  - `tests/test_chatgpt_local_server.py`

Before doing anything else in the future, run:

```bash
cd /Users/breisma1/Projects/endnote-mcp
git status
```

## What worked

### Local app

This is the smoothest working path so far.

Run:

```bash
cd /Users/breisma1/Projects/endnote-mcp
source .venv/bin/activate
export OPENAI_API_KEY="..."
endnote-mcp serve-app
```

Then open:

```text
http://127.0.0.1:8080
```

### Local MCP server for ChatGPT tunnel testing

This also worked technically.

Run:

```bash
cd /Users/breisma1/Projects/endnote-mcp
source .venv/bin/activate
export ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN="choose-a-random-secret"
endnote-mcp serve-chatgpt-local
```

Then test locally:

```bash
curl -i http://127.0.0.1:8787/health \
  -H "Authorization: Bearer $ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN"
```

This returned:

- `HTTP/1.1 200 OK`

### ngrok

ngrok was installed locally in:

```text
~/.local/bin/ngrok
```

It successfully exposed the local MCP server with a public HTTPS URL.

Example successful forwarding seen during this session:

```text
https://swagger-massive-moustache.ngrok-free.dev -> http://localhost:8787
```

## What failed / blocked progress

### ChatGPT connector auth mismatch

This was the main blocker.

When attempting to connect the ngrok-backed MCP server in ChatGPT Developer Mode, ChatGPT showed:

```text
Error fetching OAuth configuration
MCP server ... does not implement OAuth
```

Meaning:

- ChatGPT could reach the remote MCP URL
- the tunnel itself was not the core problem
- ChatGPT expected an auth model compatible with its connector setup flow
- our server currently uses custom bearer-token auth, not OAuth

### Why this matters

OpenAI’s current docs indicate ChatGPT custom MCP setup expects either:

- `OAuth`
- or `No authentication`

Our `serve-chatgpt-local` currently does:

- custom bearer-token auth

That worked for:

- `curl`
- direct local validation

But it did **not** work for ChatGPT’s connector onboarding flow.

## Main decisions already made

### Chosen architecture directions

1. Long-term “real ChatGPT connector” path:
   - local data + remote-reachable MCP
   - likely needs either OAuth or no-auth dev mode

2. Short-term usable product path:
   - local web app backed by the OpenAI API

### Security posture

We explicitly discussed that:

- no-auth mode would be acceptable only as a short-lived personal dev/demo mode
- OAuth is the more correct long-term path for ChatGPT connector compatibility
- the local web app is the least operationally messy option right now

## Most likely next paths

### Path A: add temporary no-auth dev mode

Best if the goal is:

- “I want to test this in ChatGPT soon”

Work would likely include:

- adding `--no-auth-dev` or equivalent config/env toggle to `serve-chatgpt-local`
- loud CLI and README warnings
- possibly disabling `read_pdf_section` in no-auth mode to reduce exposure

### Path B: implement real OAuth

Best if the goal is:

- “I want the ChatGPT connector path to be durable and correct”

Expected effort discussed:

- minimal single-user dev OAuth: roughly `1–2` solid engineering days
- more correct/durable version: roughly `3–5` days

This is the path needed if ChatGPT connector auth should work without dropping to no-auth mode.

### Path C: ignore ChatGPT connectors for now and keep pushing the local app

Best if the goal is:

- “I want a usable research assistant soon, not connector plumbing”

This is the easiest path operationally and already mostly works.

## Practical commands for restarting work

### Activate repo-local environment

```bash
cd /Users/breisma1/Projects/endnote-mcp
source .venv/bin/activate
which endnote-mcp
endnote-mcp --help
```

Important:

- do **not** rely on a globally installed `endnote-mcp`
- there is/was also an older install in PATH for Claude use
- use the repo `.venv` explicitly

### Re-run tests

```bash
.venv/bin/pytest -q
```

### Start local app

```bash
export OPENAI_API_KEY="..."
endnote-mcp serve-app
```

### Start ChatGPT-local MCP server

```bash
export ENDNOTE_MCP_CHATGPT_LOCAL_TOKEN="choose-a-random-secret"
endnote-mcp serve-chatgpt-local
```

### Start ngrok

```bash
~/.local/bin/ngrok http 8787
```

## If picking this up again

Recommended order:

1. Check `git status`
2. Decide whether to commit or discard the current uncommitted ChatGPT-local changes
3. Re-run tests
4. Choose one path before coding:
   - no-auth dev connector mode
   - real OAuth
   - local app UX/product improvements

My recommendation if the goal is speed and sanity:

- keep using / improving `serve-app`

My recommendation if the goal is specifically “inside ChatGPT”:

- implement temporary no-auth dev mode first
- only do OAuth after proving the connector workflow is worth the added complexity
