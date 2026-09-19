---
name: hle-expert-answer
description: How to answer a hard expert-level exam question and submit it so it is graded correctly. Use on every task that gives you a question and asks for an explanation, an answer and a confidence.
---

# Answering an expert-level question: think, commit, save

A judge extracts the single final answer from `/logs/agent/response.txt` and
compares it with a reference. All or nothing. No file, or no clear answer, is zero.

## The whole procedure: five tool calls

1. `file_editor` `view` `/app/instruction.md`.
2. `think`: reason the problem through completely (see below). This is where the
   answer comes from. Take as long as you need inside this one step.
3. `file_editor` with `command: create`, `path: /logs/agent/response.txt`,
   `file_text:` exactly

   ```
   Explanation: <3-6 lines: the route to the answer>
   Answer: <one bare final answer>
   Confidence: <number>%
   ```

   All three arguments are required. Never save an empty file.
4. Optional, **only if the question is computational** (arithmetic, counting,
   enumeration, simulation, code output): one short `python3` check. Create the
   script with `file_editor` at `/tmp/s.py`, run `python3 /tmp/s.py`. Standard
   library only. If the result disagrees with your answer, find out why, then
   overwrite the response file with the corrected three lines.
5. `finish`.

Hard limits: no more than 8 tool calls in total. No `pip`, `apt-get` or network
(none works). Never try to decode, render or OCR an image file: you cannot see
it, and the question text is enough to answer from. Every turn is a tool call; a
plain text message ends the run with nothing saved.

## How to think (step 2)

- Restate exactly what is asked: which quantity, which units, which form, which
  output format. Answer the question as literally written, even when it looks
  unusual, and copy the requested format character for character.
- Recall the governing principle, named reaction, theorem, algorithm or standard
  result. Expert questions usually hinge on one non-obvious fact or a trap in the
  wording: look for it ("what would a specialist notice that a student misses?").
- Derive the answer step by step. Then attack it: limiting cases, units,
  order of magnitude, a second method, or substituting back.
- **Multiple choice:** evaluate every option, eliminate the ones that are surely
  wrong, and choose among the rest. Answer with the option letter exactly as
  labelled. Beware options that are true statements but do not answer the question.
- **Chemistry:** write out the mechanism and count atoms; for a formula, tally C,
  H, N, O and charge explicitly; name compounds in the style the question uses.
- **Code questions:** trace the code exactly as written for the stated language
  version; when it can be executed, execute it (step 4) instead of guessing.
- **Engineering / signals / control:** write the defining formula first, keep
  symbols until the end, then substitute numbers; mind conventions (one-sided vs
  two-sided, radians vs hertz, peak vs RMS, indexing from 0 or 1).
- If you cannot fully solve it, still commit to the most probable single answer.
  Never write "cannot be determined" unless that is truly the answer.

## The Answer line

One answer, bare: the value, expression, name, list or option letter. No
"approximately", no alternatives, no restating the question. Requested units,
rounding, ordering and form. If several answers satisfy the conditions, give the
most conventional one only. Keep every caveat in `Explanation`.
