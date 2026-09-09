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

Its `<style>` block is a working implementation of §13.1 — six type sizes,
three weights, the 4px spacing grid, `--radius-sm`, and `:focus-visible` on
every interactive element — so Task 22 can lift from it rather than deriving
it a second time. Two differences are deliberate:

- The console's tokens are scoped to `.console[data-scheme="light"|"dark"]` and
  **hardcoded**, so both themes render side by side whatever theme the reader
  is in. The real page uses `@media (prefers-color-scheme: dark)`.
- Every selector is prefixed `.console` so the mockup's own page chrome does
  not collide with it.

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
