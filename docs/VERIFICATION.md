# Verification record

Manual (X) tests and local runs of the CI steps, for version 0.1.0. Each test names its ID in `docs/REQUIREMENTS.md`.
All runs used scratch folders that were deleted after the run. No real transcript content went into the repo.

## Machines

| Machine | OS | Python | Claude Code |
|---|---|---|---|
| Linux laptop | Arch Linux, kernel 7.2 | 3.14.7 | 2.1.296 |
| Mac | macOS 26.5.1 (developer tools present) | 3.9.6 (`/usr/bin/python3`) and 3.14.6 (Homebrew) | 2.1.310 |

## Automated tests and CI steps, run locally (2026-11-02, final fix round)

| Check | Linux | macOS |
|---|---|---|
| Unit and integration tests (93) | pass (3.14.7) | pass on 3.9.6; pass on 3.14.6 (see note 1) |
| T-93 recording cost, 5,000 messages, 20,000-line ledger | median 0.19 s (budget 2 s) | median 0.10 s (budget 4 s) |
| T-114 hook process return time | p95 114 ms (budget 200 ms) | p95 48 ms (budget 200 ms) |
| Secret scan with self-test (T-52, T-53) | pass, 0 hits | pass, 0 hits |
| Aggregate checks with self-test (T-50, T-51, T-135) | pass | pass |
| Manifests (T-89), versions, standard library only (T-91) | pass | pass |
| README lint and README numbers (T-111, T-112, T-109) | pass | pass |
| `claude plugin validate .` | pass | not run |

Note 1: the first macOS run on Python 3.14.6 had one error that four later runs didn't repeat. The likely cause was a
sync test that read the status file a moment before the detached sync wrote it. That test now waits for the status;
the suite then passed twice more on 3.14.6 and once on 3.9.6.

GitHub CI hasn't run yet: the repo has no remote. Python 3.9 on the `macos-latest` runner and the 200 ms hook budget
on a hosted runner are still to be seen on the first CI run.

## Install tests (2026-11-02, final fix round)

| ID | Test | Linux | macOS |
|---|---|---|---|
| T-88 | Scratch home with its own `Stop` hook; `claude plugin marketplace add <repo>`, `claude plugin install measured-estimates@measured-estimates`; the person's own `hooks` keep the same JSON value | pass (Claude Code adds `enabledPlugins` and `extraKnownMarketplaces`) | pass |
| T-97 | `claude plugin details` lists 1 skill and 2 hooks (SessionEnd, Stop) | pass | pass |
| T-87 (part) | The installed SessionEnd hook command, run with a generated 5,000-message transcript; the hook's process group is killed 50 ms after start, as a host does at its timeout; the line still arrives | pass (5,000 messages; hook command p95 90 ms over 20 runs) | pass (5,000 messages, tag kept; hook command p95 66 ms; Python found with `PATH=/usr/bin:/bin`) |
| T-142 | After the record, every folder is 0700 and every file 0600 | pass | pass |
| T-88, T-134 (part) | `claude plugin uninstall`; the person's own `hooks` keep the same JSON value | pass | pass |

## Real sessions (Linux, 2026-11-02, final fix round)

These used the author's normal login on the Linux laptop. The plugin was loaded for each session with
`claude -p --plugin-dir <repo>`; the data folders pointed at a scratch folder (`XDG_*_HOME`). No credential file was
copied. Each prompt carried `ITEM: process:install-test`.

| ID | Test | Result |
|---|---|---|
| T-87 | A real session ends; one ledger line arrives with the tag, the model and the effort level; the file is 0600 and its folder 0700 | pass (1 message, tag `process:install-test`, effort `medium`) |
| T-118 | `--resume <id> --fork-session`: the fork's line skips the copied message (`duplicate_messages: 1`) and counts only its own | pass |
| T-134 | An agent, from the skill text alone, sets up, writes its guess first, runs `estimate` and stores the estimate for a task | pass (event stored; guess recorded before the range was shown) |
| T-134 (part) | A session without the plugin writes nothing; the store is unchanged | pass |

## Real sessions on macOS

Manual, by the author. The scratch home on the Mac isn't logged in, and test runs never use the Mac's real
`~/.claude`. Steps for the author:

1. Install the plugin as the README says, in a normal session.
2. End the session, then run `ledger report`. Check that the session shows in the count.
3. Run `claude --resume <id> --fork-session`, end it, and check that the report's token total didn't double.
4. On a Mac without the developer tools (if one is at hand): end a session and check that no dialog appears.

The macOS guard against the developer-tools dialog (T-115) is tested with fake programs only. The Mac has the
developer tools, so the real no-tools path wasn't run.

## Earlier runs (Phase 3, 2026-11-02, before the final fix round)

The same Linux and macOS install tests passed on commit `e448587`'s code. The Linux real-session tests then ran in a
scratch home with a temporary copy of the login file, deleted right after. That method is no longer used. The real
sessions above replace those runs.
