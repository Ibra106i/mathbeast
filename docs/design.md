# Architecture

## Three primitives

| Primitive | What it is | Involves an LLM? |
|---|---|---|
| **Skill** | A data file that generates a question, its answer, and its worked steps *by construction* | No |
| **Checker** | Form-aware equivalence on SymPy, returning one of four states | No |
| **Narrator** | Receives verified steps and explains them | Yes, and only here |

A problem is correct by construction because the answer is never found by
searching for it — the generator picks the numbers and the engine applies an
audited transform. There is nothing in the file to get wrong.

The narrator is the only component that can be wrong, and it is structurally
bound: it emits one utterance per verified step, and `prose.py` rejects any
mathematical claim in its output that no verified step supports.

## Layout

| Module | Responsibility |
|---|---|
| `verify.py` | Four-state equivalence, strict allowlist parser, cross-platform timeout |
| `forms.py` | Answer forms: `exact`, `rounded`, `set`, `interval`, `pair` |
| `skill.py` | The skill schema, the audited `TRANSFORMS`, parameter resolution, `smoke()` |
| `prose.py` | Binding and grounding for narration; the unsupported-claim rate |
| `narrate.py` | The narrator itself, offline and via Ollama |
| `cli.py` | `drill`, `explain`, `skills`, `coverage`, `bench` |
| `skills/*.yaml` | The 0580 pack |

## The four-state checker

SymPy's `simplify` can both hang indefinitely and return `False` for expressions
that are true but unprovable. A boolean checker therefore lies in two
directions. `verify.py` returns:

| State | Meaning |
|---|---|
| `PROVEN_EQUAL` | equivalence proved |
| `PROVEN_DIFFERENT` | non-equivalence proved |
| `UNKNOWN` | timed out, or unprovable — **not** the same as wrong |
| `UNPARSEABLE` | not valid input for this answer form |

`UNKNOWN` is deliberately not `PROVEN_DIFFERENT`. The badge this project
publishes is only honest if those two stay distinct.

Escalation order, because `simplify` on everything makes the latency column
unreadable: numeric probe at fixed rational points → `simplify` → `equals`.

Timeouts use a `ProcessPoolExecutor`, because a hung thread cannot be killed
and `signal.alarm` does not exist on Windows. On timeout the pool is destroyed
and rebuilt, since the stuck worker never returns.

## The parser is a trust boundary

A student types into a drill, and a narrator emits prose. Neither may reach
code execution.

- Character allowlist before parsing.
- Dunder identifiers and reserved words rejected.
- **Superscripts rejected before NFKC.** NFKC rewrites `x³` to `x3`, which
  parses as `x*3` — silently turning a typo into a confidently wrong
  comparison. A rejection is recoverable; a misread is the exact bug this
  project exists to prevent.

## SymPy is part of the trust boundary

The guarantee is a claim about a *specific CAS version*. An out-of-range SymPy
does not fail loudly — it computes, and answers differently. So:

- `sympy>=1.12` is enforced at import
- a weekly CI canary runs the suite against newest SymPy; that job deliberately
  does not pin

This is not hypothetical. During development SymPy 1.14 removed
`solve_inequalities` from the top level, renamed `Interval.left_closed` to
`left_open`, and dropped `Expr.coeff(x, 1)`. Each was found by running the
suite, not by reading a changelog.

## What the gates protect

Every skill must clear six checks on every seed, in `tests/test_packs.py`. The
load-bearing one is that the engine's answer **verifies against the project's
own checker** under the answer form the skill declares. If those two ever
disagree, "verified by construction" is false, and that is where it surfaces.

Two of the gates have caught real errors in this repository rather than only
synthetic ones: the tier/section consistency check rejected a trigonometry
skill assigned to a section (`E6`) that does not exist in 0580, and rejected a
probability skill under `E7`. Chasing the second exposed a worse bug — the
check itself assumed Extended content always lives under an `E` section, which
is false, because the specification marks Extended content *inside* Core
sections ("C8.4 Extended content only").

## Measured, not asserted

The offline unsupported-claim rate is trivially zero and is not the number
worth publishing. The comparison — raw model vs chain-of-thought vs verified
narration — is not yet run, and the README says so rather than showing a table
nobody has produced.
