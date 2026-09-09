# Console visual reference — §13.1

What the operator console looks like once **Task 22** lands. §13.1 of the spec
is a written system — token tables, a type scale, spacing rules — and it was
written from reading `web/static/index.html`, not from looking at the rendered
page. These are the rendering, so the spec can be reviewed against something
real.

| File | What it is |
|------|------------|
| `console-13-1-light.png` | The review gate, light theme — the default |
| `console-13-1-dark.png` | The same screen under `prefers-color-scheme: dark` |
| `console-13-1-mockup.html` | The source both were shot from |

The state shown is the escalation beat: extraction finished, 28 fields
verified, and `beneficial_owners[1].dob` outstanding — §8.4's deliberate gap,
which is the screen the demo lands on.

## This is a mockup, not the console

`web/static/index.html` is the console. This page only *looks* like it. It
exists so §13.1 could be approved before any CSS moved, and it carries no
gateway polling, no JavaScript and no real state.

Its `<style>` block implements §13.1 for the rules it covers — six type sizes,
three weights, the 4px spacing grid, `--radius-sm`, the token set including
`--done-ink` / `--alert-ink`, and `:focus-visible` on the controls it shows —
so Task 22 can take the worked values from it rather than deriving them a
second time.

**It is not a drop-in replacement for the console's stylesheet.** Its 94
`.console` rules cover the happy path only; nine classes the real page uses
have no rule here, and every one is a failure-path surface this page never
renders: `.errline`, `.msg` (and its `.is-alert` / `.is-done` tones),
`.pill.is-idle`, `.pill.is-running`, `.stepper li.is-failed`,
`table.fields td.empty`, `td.val.is-edited`, `.gap input.is-empty`, and
`input.cell-edit` — which is also why `input.cell-edit:focus-visible` is
absent from the focus group. Task 22 Step 1 lists them; carry them forward by
hand onto the same tokens.

Three further differences are deliberate:

- The console's tokens are scoped to `.console[data-scheme="light"|"dark"]` and
  **hardcoded**, so both themes render side by side whatever theme the reader
  is in. The real page uses `@media (prefers-color-scheme: dark)`.
- Every selector is prefixed `.console` so the mockup's own page chrome does
  not collide with it.
- The `.stepper` applies `overflow-x: auto` and `minmax(96px, 1fr)`
  unconditionally and the page declares no `@media` at all. §13.1.4 scopes
  both to below 900px — take Task 22's Step 11 version, not this one.

**The copy is indicative, not the console's.** This page says "Commercial
Banking", "Approve", "Reject" and a one-line `.review-who`; the console says
"Commercial Onboarding", "Approve & open the account", "Reject — send back…"
and a full sentence about segregation of duties. Those strings are 3–5× longer
and land in the two flex-wrap rows, `.topbar` and `.review-actions`. Review the
*system* against these shots — type scale, spacing rhythm, colour roles — and
review wrapping against the real page in Step 14.

## Regenerating

Needs Chrome. `channel="chrome"` uses the installed browser, so nothing is
downloaded — note that `.claude/rules/testing.md` names `/opt/pw-browsers/`,
which is a container path and is absent on macOS.

```bash
uv run --with playwright python - <<'PY'
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path("docs/design")
url = "file://" + str((out / "console-13-1-mockup.html").resolve())
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(url)
    pg.wait_for_timeout(500)
    assert not errors, errors
    for scheme in ("light", "dark"):
        pg.query_selector(f".console[data-scheme='{scheme}']").screenshot(
            path=str(out / f"console-13-1-{scheme}.png"))
    b.close()
PY
```

Re-shoot these whenever §13.1 changes. A stale mockup is worse than none — it
reads as approved.
