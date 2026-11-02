# Contributing

Thank you for helping. The most useful contributions are adapters for other coding agents, and reports when the
calibration looks wrong.

## Add an adapter for another agent

The recorder reads session files through one small adapter per agent. A new agent is one file and its tests.

1. Read `scripts/adapters/base.py`. It defines the records an adapter returns: messages, prompt tags, tool events.
2. Copy `scripts/adapters/claude_code.py` to `scripts/adapters/<agent>.py`.
3. Read the session files line by line. Never read a whole file at once.
4. Keep only what the base module lists. Pass prompt text through `measured.ids.tag_lines` and keep its result only.
5. Check `deadline` every few hundred lines and raise `Deadline` when it passes.
6. Register the adapter in `scripts/adapters/__init__.py`.
7. Add an invented golden sample in `tests/fixtures/` and a test with exact token counts.
8. Add the hook or the command that runs the recorder at session end for that agent.
9. Run `python3 -m unittest discover -s tests -t tests` on macOS or Linux.

Don't put real session content in a fixture. Invent the text, the paths and the IDs.

Please test with Codex or another agent that you use, and send a pull request. Open an issue with the template
"Add support for <agent>" first if you want to discuss the format.

## Rules for every change

- Python 3.9 or newer, standard library only.
- The hook never blocks or slows a session. Every error exits 0.
- No network calls, except the sync that the person turns on.
- Every requirement in `docs/REQUIREMENTS.md` keeps a test. New behavior gets a requirement and a test.
- Update `docs/DATA.md` when you add a stored field.
- The README uses ASD-STE100 Simplified Technical English. CI checks the sentence length.

## Starter table updates

The starter table holds aggregates only. When you add data to it, add at least 5 tasks to each size bucket at a time.
Then a diff of two releases can't show the cost of one task. Run `tools/ci/check_aggregates.py data/starter.json`.

## Run the checks

```sh
python3 -m unittest discover -s tests -t tests
python3 tools/ci/scan.py .
python3 tools/ci/check_aggregates.py data/starter.json
python3 tools/ci/lint_readme.py README.md
```
