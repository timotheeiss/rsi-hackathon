---
name: hle-expert-answer
description: How to answer a hard expert-level exam question and submit it so it is graded correctly. Use on every task that gives you a question and asks for an explanation, an answer and a confidence.
---

# Answering an expert-level question

Grading is **all or nothing**. A judge model reads your response, extracts the one
final answer from it, and compares it to a reference answer. It marks you wrong on
any inconsistency, ambiguity or non-equivalence. Only numbers are given a small
margin of error. Partial reasoning earns nothing.

## Rule Zero: submit to the file

Write your answer to `/logs/agent/response.txt` in exactly this format:

```
Explanation: <brief reasoning>
Answer: <the final answer, alone>
Confidence: <number>%
```

- Nothing else is graded. If the file is missing or empty, you score zero.
- **Write a first version of the file as soon as you have any plausible answer**,
  even a weak one, then overwrite it as you improve. You have a time limit, and a
  file that exists with a guess beats a perfect answer you never saved.

## The Answer line decides everything

- Put **one** answer there, bare: the value, expression, name or option. No
  "approximately", no "either X or Y", no alternatives, no restating the question.
- Keep all reasoning, caveats and rejected candidates in `Explanation`. Never let a
  different candidate value appear as if it were your final answer.
- Give exactly what was asked for: the requested units, variable, form (fraction,
  decimal, closed form, SMILES, sequence), rounding and ordering.
- Multiple choice: give the option exactly as labelled in the question.
- Never leave it blank and never answer "I don't know" or "cannot be determined"
  unless that is genuinely the answer. An unextractable answer is a guaranteed
  zero; a committed best guess can be right.

## Use your turns

You have many turns and a generous time limit. Spend them; do not answer from a
first impression.

1. Re-read the question and write down precisely what is being asked, including
   units, the exact quantity, and any constraint that narrows the answer.
2. Solve it. Then **verify by a second, independent route**: recompute, check
   limiting cases, substitute back, or estimate the order of magnitude.
3. Use the shell as a calculator: run `python3` for arithmetic, algebra,
   combinatorics, simulation or brute force over small cases. Hand arithmetic on a
   hard problem is where answers are lost.
4. There is no internet. Standard library only unless you check a package is
   installed first; work around a missing one rather than giving up.
5. If the question refers to a figure, list the working directory and open the
   image file that is there.
6. Before you save, check the answer against the question one last time: right
   quantity, right units, right form.

## Explanation and confidence

- Keep `Explanation` short: the route to the answer, a few lines. It is not graded,
  but a contradictory explanation can mislead the extraction.
- `Confidence` is a percentage and does not change your score. Give an honest one.
