# Contributing

The shortest path to a merged PR in this repository is a YAML file. You do not
need to understand SymPy, and you do not need to write Python.

## What is welcome

**A skill.** One YAML file, one syllabus item, twenty minutes. See
[docs/authoring-skills.md](docs/authoring-skills.md), and copy
`mathbeast/skills/0580.c2.10.expand_quadratic.yaml` as a starting point.

**A corrected syllabus code.** The sub-codes below the section level are
provisional — see [docs/syllabus-map.md](docs/syllabus-map.md). If you have the
official 0580 PDF and can check a section, that is a genuinely useful
contribution.

**A new transform.** Open an issue first. Transforms are executable and go in
`mathbeast/skill.py` with tests, so it is a design discussion rather than a
drive-by PR. Keeping this small is what keeps stranger PRs safe to merge.

**A failing test.** If you find a case the checker gets wrong — especially an
`UNKNOWN` that should be `PROVEN_DIFFERENT`, or a wrong answer accepted as
right — that is a high-value bug report. A false accept is the worst thing this
project can do.

## Before you open a PR

```bash
pip install -e ".[dev]"
pytest
```

That is the whole gate. Six pack-level checks apply to every skill:

1. Schema is valid and the syllabus section is real.
2. `smoke()` finds no empty or unverifiable answer across many seeds.
3. Every generated answer **verifies against the project's own checker** under
   its declared answer form.
4. Offline narration over the steps is fully grounded.
5. No `{placeholder}` is left unrendered.
6. The statement does not contain its own answer.

You can check one skill on its own:

```bash
python -m mathbeast.cli explain <your-skill-slug>
python -m mathbeast.cli drill <your-skill-slug> --count 3
```

## House rules

**Never state an answer.** Write the *template* the answer is computed from and
name a transform. If you hardcode `answer: "42"`, the skill will fail gate 3,
and rightly so — that is the property the entire project rests on.

**`display` is literal text and is not parsed.** It substitutes parameters and
stops. Do not write maths in it expecting it to be evaluated, and never write
`^` expecting a power — that is bitwise xor.

**Do not widen the trust boundary without saying so.** The parser has a strict
character allowlist, rejects dunder identifiers and reserved words, and refuses
superscripts before NFKC normalisation. Every one of those was added because
something was silently misread. If you think a rule should be relaxed, open an
issue and describe the case it breaks.

**SymPy is part of the trust boundary.** The correctness guarantee is a claim
about a specific CAS version. Do not remove the `sympy>=1.12` floor, and do not
narrow the weekly canary — that job deliberately does not pin.

## Style

- Comments explain *why*, especially when the obvious thing is wrong. The
  codebase is full of them for a reason.
- Line length 100.
- No comments that merely restate the code.

## Code of conduct

Be decent to each other. This is a teaching tool; that is worth optimising for
in the repository as well as in the product.
