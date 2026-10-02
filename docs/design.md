# Architecture

## Three primitives

| Primitive | What it is | Involves an LLM? |
|---|---|---|
| **Skill** | A data file that generates a question, its answer, and its worked steps *by construction* | No |
| **Checker** | Form-aware equivalence on SymPy, returning one of four states | No |
| **Narrator** | Receives verified steps and explains them | Yes, and only here |

A problem is correct by construction because the answer is never computed by
searching for it — the generator picks the answer first and builds the question
around it. There is nothing to get wrong.

The narrator is the only component that can be wrong, and it is structurally
bound: it emits one utterance per verified step, and `prose.py` rejects any
mathematical claim in its output that no verified step supports.

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

## SymPy is part of the trust boundary

The guarantee is a claim about a *specific CAS version*. An out-of-range SymPy
does not fail loudly — it computes, and answers differently. So:

- `sympy>=1.12` is enforced at import
- a weekly CI canary runs the false-accept suite against newest SymPy; that job
  deliberately does not pin

## Measured, not asserted

`tests/test_false_accepts.py` runs the verifier over perturbed answers drawn from
GSM8K and MATH and asserts zero accepts. The count in this README is produced by
running it, never hardcoded.