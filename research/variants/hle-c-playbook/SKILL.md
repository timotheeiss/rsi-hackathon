---
name: hle-expert-answer
description: How to answer a hard expert-level exam question and submit it so it is graded correctly. Use on every task that gives you a question and asks for an explanation, an answer and a confidence.
---

# Answering an expert-level question

A judge extracts one final answer from `/logs/agent/response.txt` and compares it
with a reference: all or nothing. The file must read exactly:

```
Explanation: <a few lines>
Answer: <one bare final answer>
Confidence: <number>%
```

## Phase 1 (tool calls 1-2): read, then save a guess

1. View `/app/instruction.md`.
2. Immediately `file_editor` `create` `/logs/agent/response.txt` (`command`, `path`
   and `file_text` are all required) with your best first-impression answer in the
   three-line format. Not empty, not "TBD": a real answer. Runs get cut off without
   warning; this guess is your insurance.

## Phase 2 (at most 12 more tool calls): solve it twice

Classify the question, then follow the matching play. Use `think` for reasoning.

**Computable** (numeric result, counting, code output, fill-the-gaps code puzzle,
search over a small space, signal/matrix arithmetic):
write `/tmp/s.py` with `file_editor` `create`, run `python3 /tmp/s.py`. Standard
library only (`fractions`, `itertools`, `cmath`, `math`, `decimal`). Do not
hand-compute what Python can compute. If a search returns several solutions,
print them all, then pick the one the question's wording points to (the most
natural or idiomatic one) and give only that.

**Knowledge / conceptual** (mechanism, named reaction, product, definition, theory
of computation, ML theory, standards, materials): no tool will help. In `think`,
produce two independent arguments for the answer (for example forward mechanism
and atom/charge bookkeeping; or a proof sketch and a small counter-example test).
If they disagree, find the flaw before choosing.

**Multiple choice:** judge every option true/false on its own first, then pick.
Answer with the letter exactly as labelled. If two options survive, choose the
one that answers the question asked most specifically.

**Chemistry specifics:** balance atoms and charge explicitly; for molecular
formulae count C, H, N, O one fragment at a time and include the charge sign if
the species is an ion; give names in the same style as the question (IUPAC vs
trivial, "ion"/"cation" as used).

**Engineering specifics:** write the defining formula, keep symbols to the end,
check units and conventions (0- vs 1-indexing, Hz vs rad/s, peak vs RMS,
one-sided vs two-sided). Report in the units and precision requested.

**Read literally.** Answer exactly what is written, even if it seems odd: if it
asks for an N-point result, return N values; if it specifies an output template
such as `[A: 1, B: 2]`, reproduce that template character for character.

### Things that never work here (do not try them)

- Looking at an image: you cannot see it and there is no OCR. No ASCII rendering,
  pixel dumps, Pillow/OpenCV hunting, or calls to a model API. The text of the
  question identifies the system; answer from it.
- `pip install`, `apt-get`, downloads: there is no network.
- Multi-line heredocs in the terminal (often rejected): use a script file.
- A plain text message instead of a tool call: it ends the run.
- More than about 14 tool calls: long runs here have always ended with no answer.

## Phase 3 (last 2 tool calls): commit

1. Overwrite `/logs/agent/response.txt` with the final three lines. `Answer:` holds
   **one** bare answer: no "approximately", no "or", no alternatives, no sentence.
   Never "I don't know" or "cannot be determined" unless that is genuinely the
   answer. Keep `Explanation` short and consistent with the answer: mention no
   rival candidate values there. Confidence is an honest percentage.
2. `finish`.
