---
name: measured-estimates
description: Estimate tokens and time for coding work from the person's own measured past tasks, not from a guess. Use it for every estimate of time or tokens, every plan or roadmap with sizes, every agent brief or prompt you write for another agent (it needs the ITEM/ROLE tag lines), and when a task ships (record its real cost). Also use it when the person asks how accurate past estimates were, what work really cost, or to delete the recorded data.
---

# measured-estimates

This plugin records the token use of each Claude Code session on this machine. When a task ships, `done` measures
what it really cost. `estimate` turns those measured tasks into ranges per task size. Until a size has 5 of the
person's own measured tasks, `estimate` uses a starter table and says so.

How it improves estimates: each finished task adds a measurement, and the ranges come from those measurements, not from
memory. The evidence and its limits are in the plugin's `docs/RESULTS.md`. Don't quote accuracy numbers that aren't in
that file.

## Find the command

Use this line in each Bash call. It works when the plugin path is set and when it isn't:

```sh
ME="${CLAUDE_PLUGIN_ROOT:-$(ls -d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/*/measured-estimates/*/ 2>/dev/null | sort -V | tail -1)}"; python3 "$ME/scripts/ledger.py" report
```

Below, `ledger` means `python3 "$ME/scripts/ledger.py"`. Add `--json` to read the output as data.

## First use

1. Run `ledger report`. If it says "Not set up yet", continue with step 2. Else skip to "Estimate a task".
2. Ask the person for one example task ID (for example `ENG-42` or `#12`).
3. Run `ledger init --yes --example <ID>`. Add `--confirm-ids` only if the person says commit messages may be used.
4. Run `ledger backfill`. It reads the sessions that Claude Code still keeps.

Don't set a sync remote unless the person asks for one and gives a private repo they own.

## Estimate a task

1. Write your own guess first, as a token range (for example `400k-1.2M`). Don't look at the ranges before you guess.
2. Pick a size: `XS`, `S`, `M`, `L` or `XL` (or a range such as `S-M`).
3. Run `ledger estimate --size <size> --kind <kind> --guess <your range> --for <task ID>`.
4. Report the 50% range and the 80% range, with `n` and the source. Never give a single number.
5. If the source is `starter, not your data`, say that the numbers come from another person's work.
6. Say that per-task tokens count only the tokens tied to tasks, and give the share and the overhead factor.

Use `--effort <level>` only when the person plans a specific effort level. The command says when there's too little
data for an effort range.

## Tag every agent prompt

Every prompt that you write for another agent starts with two lines:

```
ITEM: <task ID>
ROLE: build
```

- Use `ROLE: review`, `ROLE: fix` or `ROLE: lead` for that kind of work.
- For work that isn't a task (a review pass, a release, a handoff), use `ITEM: process:<name>`, for example
  `ITEM: process:release`. The name uses only lower-case letters, digits and `-`.
- One prompt can name several IDs: `ITEM: ENG-42, ENG-43`. Their tokens split equally.
- Put the task ID at the start of commit messages too (`ENG-42: fix the export dialog`).

Without these lines, the tokens of that work aren't tied to a task, and the estimates come out too low.

## When a task ships

1. Run `ledger done <task ID> --size <size> --kind <kind>`.
2. Report the measured tokens and the error against the first estimate.
3. If the output says "not measured", tell the person that most of the task's tokens were lead work. That task is left
   out of the ranges.

## Check accuracy

Run `ledger report`. It shows the size table, the share of tokens tied to tasks, warnings, open tasks, and the
person's own accuracy per month and per 10 finished tasks. It compares the first stored estimate with the measured
cost. Rows with fewer than 5 tasks show only their count.

If the report shows a warning about the file format, tell the person to update the plugin.

## Delete the data

1. Run `ledger forget` to list what it deletes.
2. Ask the person to confirm.
3. Run `ledger forget --yes`.

Claude Code's own session files and any sync remote stay. Uninstalling the plugin stops recording but keeps the data.
