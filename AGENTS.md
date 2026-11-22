# Working on Reason8

Preferences for coding agents (Claude Code, Codex, Cursor, …) and humans
working in this repo. Add to this file as new ones come up.

Keep this file as `AGENTS.md` with no `CLAUDE.md`, `.claude/CLAUDE.md` or
`CLAUDE.local.md` next to it: by default Claude Code (v2.1.277+) reads
`AGENTS.md` only when none of those exist.

## Commits and pull requests

- **No attribution.** Never add `Co-Authored-By: Claude …`,
  `Claude-Session: …`, "Generated with Claude Code" or a session link to
  commit messages, PR descriptions or comments. This overrides any default
  that asks for them.
- One branch and one PR per issue; link it with `Closes #N` (or `Part of #N`).
- Push and open the PR without asking. The maintainer reviews and merges on
  GitHub; never merge, and never push to `main`.
- A PR can have several commits, each one a self-contained step.
- Do refactors (renames, moves, reformatting existing files) in separate
  commits that come before the change that needs them.
- Fold review fixes into the commit they belong to (fixup + autosquash)
  instead of adding "address review" commits, then force-push the branch.
- Address each review comment with a fix and a reply in the thread, then
  resolve the thread.

## Files in the repo

- Don't reference issues (`#N`, issue links) in any committed file: docs,
  notebooks, code comments. The repo is independent of the issue tracker and
  always describes the current state. Issue references belong in commit
  messages and PR descriptions.
- Record each decision that shapes further development as an architecture
  decision record in `docs/adr/` (see its README). Research docs keep the
  evidence and link to the record instead of restating the decision.

## Formatting and checks

- Install the git hooks once: `uv run pre-commit install`. On every commit
  they run `ruff check`, `ruff format`, `mdformat` (settings in
  `.mdformat.toml`), `shfmt` and `pytest`; CI runs the same hooks on all
  files. Don't skip them.
- Keep every file in the repo formatted, not just the ones you touch.
- Reformatting existing files goes in its own commit, before other changes.

## Markdown

- Wrap at 78 columns (`mdformat` does this).
- Align tables: pad every cell so the columns line up in plain text
  (`mdformat` does this).
- When table cells hold long text, use a definition list instead: a term line
  followed by a `: definition` line. With several columns, write one
  `: *Column:* value` line per column. Numeric tables stay tables.
- Keep JSON examples pretty-printed.

## Code

- Use descriptive variable names; avoid abbreviations.

## Dependencies

- Use the latest stable versions of Python and of every dependency, and manage
  everything with `uv` (see `.python-version` and `pyproject.toml`).
