# Home surface: the remaining phases

Twenty pushes, one phase each, the app runnable after every one. Phases 1 to 8
are in `git log`. This file is the plan for 9 through 20, because the plan for
them was living in a conversation and would not have survived it. All twenty
are delivered; the rows below stay as the record of what each one promised.

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
| **P12** | Missing interactive states. `.navitem` and `.btn` have hover but no `:focus-visible`; the topbar's brand link and the status bar's `select` have neither; nothing has `:active`. The original row named `.pill`, `.status-pill` and `.backenddot` as controls that needed all three, and none of the three survives inspection: the pill and the dot are spans, and `.status-pill` is not a class in the code at all. Hover on something that cannot be pressed is a promise the page cannot keep. |
| **P13** | A motion system. Exactly two transitions exist today (`chromebtn`, `drawer-link`), and the sidenav — the drawer's twin since P11 — is not one of them: the same row moves on one shell and snaps on the other. The composer's focus ring and the title's underline snap too. All of it on `--fast` / `--med` / `--ease`, with `prefers-reduced-motion` honoured. The pills do not move, because nothing about them ever changes state, and the drawer does not slide, because `hidden` is what keeps it correct without JS. |
| **P14** | Accessibility pass: focus order through the new bottom row, drawer focus containment and return, `aria-live` on the status chip, and a contrast audit of every token pair the page actually uses rather than the two we checked. |
| **P15** | Responsive. There is not one `@media` rule in either stylesheet. Stage padding, the 597px composer and the bottom row down to 360px, without changing a single measured desktop number. |
| **P16** | The backend-away state. Not in the capture, so it is ours: no models, no Ollama, the page must say so plainly and use the tokens rather than inventing a red. |
| **P17** | Pixel harness. Render at 1622x969, diff against the capture, and land the deltas it reports — `--text-title` 34 to 40, `.chrome` 44 to 32, `.stage-main` padding 126 to 171, the mark's bounding box. Skips when the capture is not supplied. |
| **P18** | Act on the harness's second report. What P17's own changes broke, and the residuals — each one either driven to zero or written down as deliberate. |
| **P19** | Title typeface. System stack against a vendored face, decided by measuring the capture's letterforms rather than by taste. |
| **P20** | Close out. Harness in CI or documented as manual, README updated, and every control still shipping `disabled` listed with what it is waiting for. |

## Not scheduled

Enabling the three controls that ship `disabled` — **New question**,
**Dictate** and **Choose model**. Each needs something real to do first: a
pack loader behind two of them, a second input mode behind the third. Deciding
*that* is a product question, not a styling phase. They are the three things
the page deliberately does not claim, and the README's "What the page does not
claim yet" table lists each one against the code — a test reads that table and
fails when a control and its row drift apart.

**Chat** and **Medium**, the mode and tier words beside them, were named here
too and should not have been. They are spans, not controls: there is no
affordance to break and nothing to disable. They stay as words on the surface
until an input mode and a verification tier actually exist.
