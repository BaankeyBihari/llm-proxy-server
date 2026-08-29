# Contributing

## Setup

```bash
mise install   # installs the pinned Python (see .mise.toml)
uv sync        # creates .venv, installs dev deps
```

## Making changes

This repo uses [linked-intent development](docs/intent/) — see `AGENTS.md` for
the full workflow (HLD → LLD → EARS → tests → code). Bug fixes walk the same
path, no shortcut.

## Tests

```bash
uv run pytest                                # full suite
uv run pytest tests/test_gateway_config.py   # one file
```

Run the suite before opening a PR; CI (`Test (pytest)`) re-runs it on every
push.

## Pull requests

`main` is protected — direct pushes are rejected. Branch off `main`, commit,
push, open a PR. The `Test (pytest)` check must pass before merge.
