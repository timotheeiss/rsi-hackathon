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
- **Your second action, straight after reading `/app/instruction.md`, is to save a
  complete first guess**: `file_editor`, `command: create`,
  `path: /logs/agent/response.txt`, `file_text:` all three lines with a real
  answer on the `Answer:` line. Never save an empty file and never postpone this.
  Do it before any calculation, script, package check or look at an image.
- Most lost tasks were lost here: the run ended (time limit, a malformed tool
  call, a provider error) before any file existed. A saved guess can be right; a
  missing file never is.
- Each time your answer changes, overwrite the file at once (`create` again with
  the full three lines). Finish by viewing the file, then call `finish`.

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

## Budget: at most 12 tool calls after the first guess

Thinking is what solves these questions; tool calls are for checking. Long runs
(40+ commands) have never produced a correct answer here and they end without a
final file. After about 12 tool calls, stop, save your best answer and `finish`.

- **Images.** You cannot see images and there is no OCR. Do not render the image
  as ASCII, do not dump pixels, do not install or hunt for Pillow/OpenCV, and do
  not try to call any model API. The question text nearly always names the
  reaction, circuit or structure: answer from the text and your knowledge. If the
  image is truly essential, give the most probable answer for that kind of
  question.
- **No installs, no network**: `pip install`, `apt-get` and downloads fail and
  waste minutes. Use plain `python3` with the standard library.
- **Running code.** Create the script with `file_editor` (`command: create`,
  `path: /tmp/s.py`, `file_text: ...` - all three are required), then run
  `python3 /tmp/s.py`. Multi-line heredocs in the terminal are often rejected.
  Keep scripts fast (seconds) and print little.
- Every turn must be a proper tool call. Do not write your thoughts as a plain
  message: a message without a tool call ends the run.

## Work the problem

1. Re-read the question and pin down precisely what is being asked, including
   units, the exact quantity, and any constraint that narrows the answer. Answer
   the question **as literally written**, even if it seems odd (if it asks for a
   4-point transform of an 8-sample sequence, give 4 values, not 8), and in the
   stated output format, character for character.
2. Solve it. Then **verify by a second, independent route**: recompute, check
   limiting cases, substitute back, or estimate the order of magnitude.
3. Use the shell as a calculator: run `python3` for arithmetic, algebra,
   combinatorics, simulation or brute force over small cases. Hand arithmetic on a
   hard problem is where answers are lost.
4. If brute force finds several answers that all satisfy the stated condition,
   prefer the most conventional, idiomatic one and give exactly one.
5. Before you save, check the answer against the question one last time: right
   quantity, right units, right form.

## Explanation and confidence

- Keep `Explanation` short: the route to the answer, a few lines. It is not graded,
  but a contradictory explanation can mislead the extraction.
- `Confidence` is a percentage and does not change your score. Give an honest one.
