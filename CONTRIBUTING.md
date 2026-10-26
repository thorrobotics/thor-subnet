# Contributing

This repository is illustrative: it shows how the subnet will work while the full platform is
built. Issues and pull requests that make the protocol, the scoring or the docs clearer are
welcome; changes to the rules themselves are decided with the launch, so open an issue first.

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```

Keep the docs and the code saying the same thing: `docs/scoring.md` and `thor/scoring.py`,
`docs/validators.md` and `validator/`, `docs/protocol.md` and `thor/schemas/`. The tests pin
the examples' scores, so a change to a rule shows up as a changed number.
