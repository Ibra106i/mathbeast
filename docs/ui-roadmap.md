# Home surface: the remaining phases

Twenty pushes, one phase each, the app runnable after every one. Phases 1 to 8
are in `git log`. This file is the plan for 9 through 20, because the plan for
them was living in a conversation and would not have survived it.

Constraints that apply to every row below:

- One push per phase. Nothing lands that leaves the app unrunnable.
- No npm, no bundler, no CDN. Jinja, HTMX and SSE are vendored.
- `tokens.css` is the only file permitted to hold a literal hex.
- A control ships `disabled` until it has something real to do, and the
  comment beside it says what it is waiting for.
- A number measured from the capture is exact; a number that was not measured
  says so in the comment where it is used.

| # | Phase |
|---|---|
| **P9** | This file. |
| **P10** | Drawer, scrim, status chip and pills onto the measured palette. The composer and tokens were re-based on the capture in P7/P8; these surfaces still carry the pre-measurement treatment. |
| **P11** | Inspector and the planned-view stubs onto the same palette, so every page speaks one set of tokens rather than the home surface being special. |
| **P12** | Missing interactive states. `.pill`, `.status-pill` and `.backenddot` have no hover, focus or active treatment; `.navitem` and `.btn` have hover but no `:focus-visible`. |
| **P13** | A motion system. Exactly two transitions exist today (`chromebtn`, `drawer-link`); composer, title and pills snap instead of moving. All of it on `--fast` / `--med` / `--ease`, with `prefers-reduced-motion` honoured. |
| **P14** | Accessibility pass: focus order through the new bottom row, drawer focus containment and return, `aria-live` on the status chip, and a contrast audit of every token pair the page actually uses rather than the two we checked. |
| **P15** | Responsive. There is not one `@media` rule in either stylesheet. Stage padding, the 597px composer and the bottom row down to 360px, without changing a single measured desktop number. |
| **P16** | The backend-away state. Not in the capture, so it is ours: no models, no Ollama, the page must say so plainly and use the tokens rather than inventing a red. |
| **P17** | Pixel harness. Render at 1622x969, diff against the capture, and land the deltas it reports — `--text-title` 34 to 40, `.chrome` 44 to 32, `.stage-main` padding 126 to 171, the mark's bounding box. Skips when the capture is not supplied. |
| **P18** | Act on the harness's second report. What P17's own changes broke, and the residuals — each one either driven to zero or written down as deliberate. |
| **P19** | Title typeface. System stack against a vendored face, decided by measuring the capture's letterforms rather than by taste. |
| **P20** | Close out. Harness in CI or documented as manual, README updated, and every control still shipping `disabled` listed with what it is waiting for. |

## Not scheduled

Enabling `+`, the mode pill and the tier badge. Each needs something real to do
first — a pack loader, a second input mode, a verification tier — and
deciding *that* is a product question, not a styling phase. They are the three
things the page deliberately does not claim. Scheduling them before the
decisions exist would be the same lie the disabled button is there to avoid.
