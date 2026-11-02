# Notes for coding agents in this repo

This repo is public. Everything you commit is visible to everyone.

## Commits
1. Commit as `iretonsean <1441621+iretonsean@users.noreply.github.com>`.
2. Don't add a `Claude-Session:` line to commit messages or pull request text. Session links don't belong in public
   history. A `Co-Authored-By:` line is fine.
3. Don't commit personal data: no names of other projects, home paths, host names, IP addresses, emails, keys or
   tokens, and no real session data. Test data is invented.
4. Prefer a pull request over a direct push to `main` for anything beyond a small fix.

## Before you push
1. Run the tests: `python3 -m unittest discover -s tests`.
2. Keep Python 3.9 support (macOS ships 3.9). Standard library only.
3. Keep `README.md` in ASD-STE100, with the ELI5 section first. CI checks the sentence length.
4. Put numbers in the README "How accurate is it?" section only if they're in `docs/RESULTS.md`.
5. When you change a requirement, update `docs/REQUIREMENTS.md` and its test in the same commit.
