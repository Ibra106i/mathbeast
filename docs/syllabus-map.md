# 0580 syllabus map

**49 skills: 39 Core, 10 Extended.** Sections covered: C1–C9, E2, E4.

`mathbeast coverage` prints the live version of this table.

## Read this before trusting a code

There are two different kinds of confidence in this file, and conflating them
would be the same error this project exists to prevent.

**Section codes (C1–C9, E1–E5) are verified.** These are 0580's topic sections,
cross-checked against Cambridge's published syllabus overview. They are also
enforced in code: `mathbeast.skill.VALID_SECTIONS`, and every skill is
rejected at load time if its section is not one of them.

**Sub-codes (C1.10, E2.3, …) are provisional.** They were reconstructed from
public summaries of the specification, not transcribed from the official PDF.
Some are certainly wrong — this pack has already been caught using `E6` and
`E7`, which do not exist, and `C1.10`–`C1.14` are sequential guesses at where
percentage content begins.

Treat the sub-code as a *label for where the content lives*, not as a citation.
Before this pack is used for teaching, or before a student is pointed at a
reference, check the sub-code against
[the official 0580 specification](https://www.cambridgeinternational.org/Images/662466-2025-2027-syllabus.pdf)
and correct the YAML. Nothing else needs to change: the code is a filename and
a field, not a computation.

A fix for this is a good first issue, and a well-scoped one.

## Coverage by section

| Section | Topic | Skills |
|---|---|---|
| C1 | Number | 11 |
| C2 | Algebra and graphs | 9 |
| C3 | Geometry | 5 |
| C4 | Mensuration | 5 |
| C5 | Coordinate geometry | 2 |
| C6 | Trigonometry | 3 |
| C7 | Probability | 2 |
| C8 | Probability (Extended content) | 1 |
| C9 | Statistics | 2 |
| E2 | Algebra and graphs (Extended) | 7 |
| E4 | Mensuration (Extended) | 2 |

## Gaps, stated plainly

These sections have **no** skills yet, and pretending otherwise would make the
coverage report a decoration:

- **E1** Number (Extended) — indices laws in depth, bounds, standard form
  arithmetic, exponential growth
- **E3** Geometry (Extended) — circle theorems, angle facts, constructions,
  loci, bearings, vectors and transformations
- **E5** Probability and statistics (Extended) — full sample space diagrams,
  Venn diagrams, combined events, histograms, scatter diagrams and correlation

Within covered sections the gaps are narrower: sequences beyond arithmetic,
algebraic fractions beyond simplification, graphs and functions, inequalities
beyond one variable, surface area of prisms and cylinders, compound shapes.

## What a skill does *not* model

Being clear about this matters more than the coverage percentage:

- **No diagrams.** Skills are text. Constructions, loci, bearings and
  transformations cannot be expressed yet.
- **No multi-step question chains** where a later part depends on a student's
  earlier answer.
- **No worded problems in the harder sense.** Statements are short and
  templated. Real exam wording is far more varied than a template can capture,
  and that is the single biggest gap between this pack and an exam paper.
