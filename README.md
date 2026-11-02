# measured-estimates

A Claude Code plugin. Your coding agent estimates tokens and time from what your own past tasks really cost.

## ELI5

- This plugin is for people who use coding agents. It helps you know what work will really cost in time and tokens.
- It works as a fuel log does for a car. You write down what each trip really used, so you learn the real fuel use.
- After each session, it records how many tokens the session used. It keeps this record on your own computer.
- When a task is finished, it measures what that task really cost.
- Before your agent gives an estimate, it looks at those real costs. Then it gives a range, not a single guess.
- It doesn't read or send your prompts or your code. It keeps only counts, times and task IDs.
- Nothing leaves your computer unless you set up sync to your own private repo.
- Each finished task adds one more measurement. So your estimates come closer to the real cost over time.

## How accurate is it?

<!-- results:start -->
All numbers here come from `docs/RESULTS.md`. They come from one developer's tasks, with a pre-registered test.

**The problem.** We compared the agent's guesses with the measured cost of 82 finished tasks, over 8 days of work.

- The measured cost was a median 0.44 of the middle of the guess.
- 51 tasks cost less than the low end of the guess. 25 were inside the guess. 6 cost more.
- The measured cost counts only the tokens tied to a task: 69% of all tokens in those weeks.
- So part of this gap comes from untied tokens, not from high guesses.

**What calibration changed.** We tested on 30 tasks, each estimated only from tasks finished before it started.

- Median error was 0.34 for the calibrated ranges and 0.56 for the guesses (0.69 means a miss by a factor of 2).
- Against the guesses: difference -0.22, 90% interval [-0.50, 0.12].
- Against the guesses with their average bias removed: difference -0.08, 90% interval [-0.29, 0.10].
- Against ranges that ignore the task size: difference -0.21, 90% interval [-0.45, 0.16].
- The 50% range held the real cost for 67% of tasks [31%, 81%]. The 80% range held it for 93% [86%, 100%].
- The bias of the calibrated ranges is unclear: 0.00, 90% interval [-0.24, 0.60].

**The verdict: inconclusive, all three comparisons and the range check.** The test points fall on 5 days. The
pre-registered minimum is 8 days. The point values favour calibration, but each interval reaches above 0.

**Not shown yet.** We can't show that accuracy improves as your own tasks replace the starter ranges. One person's
three weeks of data can't show that. On your own data, `ledger report` shows your error, coverage and bias per month
and per 10 finished tasks. It compares each first estimate with the measured cost.

**Effort level.** The data records the effort level, but most cells have fewer than 5 tasks. The results show it only
as a description.
<!-- results:end -->

## Install

1. In Claude Code, type `/plugin marketplace add iretonsean/measured-estimates`.
2. Type `/plugin install measured-estimates`.
3. Start a new session and tell your agent: "set up measured-estimates".

Your agent asks you for one example task ID, such as `ENG-42` or `#12`. Then it reads the sessions that Claude Code
still keeps on your computer (about the last 30 days).

You need Python 3.9 or newer. macOS and most Linux systems have it. On macOS without the developer tools, the plugin
doesn't record and doesn't show a dialog. To get Python, run `xcode-select --install` or install it from python.org.

## Tag your agent prompts

The plugin ties tokens to a task through two lines at the top of each agent prompt:

```
ITEM: ENG-42
ROLE: build
```

- The skill tells your agent to add these lines to every prompt it writes for another agent.
- Use `ROLE: review`, `ROLE: fix` or `ROLE: lead` for that kind of work.
- For work that isn't a task, use `ITEM: process:<name>`, for example `ITEM: process:release`.
- Put the task ID at the start of commit messages too, for example `ENG-42: fix the export dialog`.

Untagged work stays in the totals but isn't tied to a task. Then per-task costs come out too low. The report shows how
much of your work is tied to tasks.

## Worked example

You ask your agent for an estimate. The agent writes its own guess first. Then it runs the estimate. Here, `ledger`
is short for `python3 <plugin folder>/scripts/ledger.py`.

```
$ ledger estimate --size S --kind bug --guess 300k-900k --for ENG-42
S bug (starter, not your data, n 19, good):
  50% range: 200k to 640k tokens, 0.5 to 1.9 h work, 3.3 to 18 h elapsed
  80% range: 56k to 830k tokens
  Tokens tied to tasks: 45% of all tokens; total use is about x2.2 of task tokens.
  Note: S has 0 of your measured tasks; your own range replaces the starter at 5.
  Stored as the estimate for ENG-42.
```

- The 50% range holds the real cost about half of the time. The 80% range holds it about 8 times in 10.
- "starter, not your data" means the numbers come from another person's work.
- After 5 of your own finished tasks of a size, your own numbers replace the starter for that size.

When the task ships, the agent runs `ledger done ENG-42`. It records the real cost and compares it with the first
estimate. `ledger report` shows your own accuracy per month and per 10 finished tasks.

## What it stores

- Per session: token counts per model and effort level, times, task IDs, roles and a random machine ID.
- Per task: your estimates and the measured cost.
- It doesn't store prompts, replies, code, file contents, file paths, commit messages or your hostname.
- Folder names, branch names and session titles are off. You can turn each one on in the config.
- You can exclude folders with `ignore_paths`, for example for client work.

The full list of fields is in `docs/DATA.md`. The data is in `~/.local/share/measured-estimates/`, with settings in
`~/.config/measured-estimates/`.

## Delete your data

1. Tell your agent: "forget my measured-estimates data".
2. The agent shows what it will delete. Confirm it.

To do it yourself, run `ledger forget --yes`. This deletes the store, the settings and the state files. It doesn't
touch Claude Code's own session files or your sync repo. Uninstalling the plugin stops the recording but keeps the data.

## Limits

- The accuracy test so far is inconclusive: too few days of finished tasks (see above).
- It works with Claude Code only. You can add other agents with an adapter (see `CONTRIBUTING.md`).
- It runs on macOS and Linux. Windows isn't supported yet.
- The starter ranges come from one person's workflow. Treat them as a start.
- Per-task costs count only the tokens tied to tasks. The report shows that share and the overhead factor.
- The size label is your own guess. A wrong size gives a wrong range.
- Claude Code deletes old session files after a time. Backfill can read only the files that are still there.
- If Claude Code changes its file format, the counts can stop. The report then shows a warning.

## Where the starter numbers come from

One solo developer, Claude Code with Opus and Sonnet agents, one review and one fix round per task, Oct-Nov 2026.

## Contribute

To add another agent, read `CONTRIBUTING.md`. If your estimates look wrong, open an issue with the template
"Calibration looks wrong".

## Terms

- **Session**: one Claude Code conversation, with its subagents.
- **Task**: a unit of work with an ID that you choose.
- **Task ID**: the ID of a task, such as `ENG-42` or `#12`.
- **Tokens**: units of text that the model reads and writes.
- **Fresh tokens**: output tokens, new input tokens and cache-write tokens. Cache reads aren't included.
- **Range**: a low and a high value. The 50% range holds the real cost about half of the time.
- **Estimate**: the ranges for a task, made before the work starts.
- **Ledger**: the record of each session's tokens.
- **Store**: the folder on your computer that holds the ledger and the tasks.

## License

MIT. Copyright (c) 2026 Sean Ireton.
