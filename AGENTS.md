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
- Wrap commit messages at 78 columns: a short subject line, a blank line, then
  the body.
- Say in every commit message why the change is made: the problem it solves or
  the reason for each choice, not only what changed. A reviewer should not
  have to read the diff or the PR description to learn the motivation.
- Keep a commit to one change. When a message needs "and" to join two
  unrelated things, split the commit.
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

## Decisions and questions

- Ask the maintainer as soon as a decision is theirs to make, during the work,
  not at the end: a choice between approaches, a change to a recorded
  decision, anything with no clear default. Wait for the answer before
  building on one side of it.
- Before opening a pull request, ask the open questions it raises first. Don't
  leave them in the PR description to be found later.

## Files in the repo

- Don't reference issues (`#N`, issue links) in any committed file: docs,
  notebooks, code comments. The repo is independent of the issue tracker and
  always describes the current state. Issue references belong in commit
  messages and PR descriptions.
- Record each decision that shapes further development as an architecture
  decision record in `docs/decisions/` (see its README). When a decision
  changes, rewrite its record so it states what holds now. Research docs keep
  the evidence and link to the record instead of restating the decision.
- Start every research doc with a concise summary: first the verdict in plain
  words, including when the result is negative or the numbers are low, then
  what can be used from it. A reader should know the conclusion and what to do
  with it without reading the rest.

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
