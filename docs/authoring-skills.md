# Authoring skills

A skill is a YAML file. It states a question and an audited transform, and the
engine computes the answer. **There is no answer in the file to get wrong.**

That is the whole design. It also means a contribution cannot smuggle in
executable code, which is why good-first-issue PRs are welcome here.

## A complete example

```yaml
id: 0580.c2.10.expand_quadratic
syllabus: C2.10
tier: core
title: Expanding two brackets
statement: "Expand {expr}."
display: "{a}{v} + {b}{v} + {c}"
answer: "{a}*{v} + {b}*{v} + {c}"
answer_form: exact
transform: expand
rationale: "Multiply out each bracket in turn, then collect like terms."
params:
  v: { dist: const, value: x }
  a: { dist: int, range: [1, 12] }
  q: { dist: int, range: [1, 12] }
  psum: { dist: derive, template: "{a} + {q}" }
  prod: { dist: derive, template: "{a}*{q}" }
steps:
  - "Multiply out each bracket in turn."
  - "Collect the x terms: {a} + {q} = {psum}."
```

## Fields

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Must be `0580.cX.Y` or `0580.eX.Y` — a real syllabus reference |
| `syllabus` | yes | The code, e.g. `C2.10`. Its section letter must be a real 0580 section |
| `tier` | yes | `core` or `extended`. An `E`-section is always `extended` |
| `title` | yes | One line |
| `statement` | yes | The question. `{expr}` renders the question's own expression |
| `answer` | yes | A **template**, not an answer. SymPy evaluates it, then `transform` runs |
| `answer_form` | yes | `exact`, `rounded`, `set`, `interval`, `pair` |
| `transform` | no | Defaults to `simplify` |
| `spec` | with `rounded` | `"3sf"` or `"2dp"`. May reference parameters: `"{sf}sf"` |
| `display` | no | Overrides how the question is written. Literal text — see below |
| `params` | no | How to choose the numbers |
| `steps` | no | Verified working. If absent, `rationale` becomes a single step |
| `rationale` | no | Shown if `steps` is absent |

### `display` is literal, and that matters

`display` substitutes parameters and stops. It is not parsed as maths. Two
reasons:

- `13^2` is Python's bitwise xor. Parsing a display string as maths yields 15.
- Canonicalising destroys the question. SymPy renders `15*x + 8*x` as `23*x` —
  which is the answer. A skill asking "simplify 15x + 8x" would otherwise
  state its own answer in the stem.

## Parameter distributions

| `dist` | Example | Meaning |
|---|---|---|
| `int` | `{ dist: int, range: [2, 9], exclude: [0] }` | Uniform integer in range |
| `choice` | `{ dist: choice, options: [3, 5, 8] }` | One of the listed values |
| `const` | `{ dist: const, value: x }` | A fixed value |
| `derive` | `{ dist: derive, template: "{a}*{b}" }` | An expression over already-bound parameters |
| `sign` | `{ dist: sign, from: b }` | Renders a number as `"+ 11"` or `"- 11"` for display |

`derive` may reference other parameters and resolves in dependency order.
`sign` reads an existing parameter via `from:` — use that, not `of:`, or it
will draw a fresh value that disagrees with the one it displays.

## Transforms

The audited vocabulary. All deterministic, all unit tested.

`expand` · `collect` · `factor` · `simplify` · `solve` · `roots` ·
`solve_ineq` · `solve_system_x` · `complete_square` · `powsimp` · `exact` ·
`numeric` · `diff` · `integrate` · `sqrt` · `sort_set`

`solve`, `roots` and `sort_set` produce a list of values, so they require
`answer_form: set`. This is enforced.

### If your question needs a transform that does not exist

Open an issue first. Adding one means it goes into `TRANSFORMS` with tests,
which is a design decision rather than a contribution — and it is the only
place executable logic belongs.

## The gates your skill must pass

Run `pytest` before opening a PR. A skill is rejected unless, for many seeds:

1. The schema is valid and the section code is real.
2. `smoke()` finds no empty or unverifiable answer.
3. Every answer **verifies against the project's own checker** under the
   declared answer form.
4. Offline narration over its steps is fully grounded.
5. No `{placeholder}` is left unrendered.
6. The statement does not contain its own answer.

Gates 3 and 4 are the interesting ones. If the engine's answer does not
satisfy the checker we ship, the claim "verified by construction" is false,
and that is where it surfaces.

## Checklist for a good skill

- Does every seed produce a question a real teacher would ask?
- Are the parameter ranges pedagogically sensible (3-4-5 for Pythagoras,
  squares to 15 for recall, clean percentages)?
- Do the steps teach the method, not just restate the answer?
- Is `rationale` one honest sentence explaining why this is in the syllabus?
