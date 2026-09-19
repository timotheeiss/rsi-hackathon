---
name: health-conversation-reply
description: How to write the final reply in a health conversation. Use on every task that asks you to reply to a user or clinician about symptoms, conditions, medications, test results or medical records.
---

# Replying to a health conversation

> **RULE ZERO: only the output file is graded.** Your first action is one
> `file_editor` call with **all three** arguments: `command: create`,
> `path: <the output path named in the task>`, `file_text: <the whole reply>`.
> Then call `finish`. You have about four turns: no `mkdir`, no exploring.
> If the tool says `file_text` is required, repeat the call with the reply inside
> `file_text`. Never send the reply as a chat message: a message is not graded.
> The file holds only the reply itself.

## Predict the grader's checklist, then satisfy it

A physician wrote a hidden checklist for this exact conversation: items that add
points and items that subtract them. Before writing, silently list at least
eight things a specialist in this field would check in your reply. They come
from these families:

1. **Opening.** What must the first sentence be: call emergency services now /
   get seen today / "I need to know X first" / "this decision belongs to your
   specialist, here is how it is usually made" / the direct answer?
2. **Missing context.** Which few facts would change the advice (the exact
   symptom, age, pregnancy, medicines, duration, measurements, what was tried)?
   Ask for those by name and say why each matters.
3. **Specialist specifics.** The named cause, test, threshold or treatment stage
   an expert would expect to see mentioned, at the depth this reader can use.
4. **Safety.** Red flags specific to this problem with where to go; for each
   medicine, who must avoid it (pregnancy, breastfeeding, children, kidney/liver,
   interactions).
5. **Document integrity** (if a note, letter or summary is requested): always
   produced, standard sections, every supplied detail in its proper section,
   nothing added that the user did not supply, gaps marked, assumptions and the
   details still needed listed after it.
6. **Tone and form.** Concise, key actions in bold, plain language for lay users,
   warmth and "you are not alone" when the person is distressed.

Then predict the penalties: a fact you are not sure of; a diagnosis, stage or
reassurance without findings; invented dates, values or reasons; calling a
standard test optional; alarm for a non-emergency; length and padding; questions
when context was already sufficient.

Write so that each predicted item gets one clear sentence or line, most important
first. Covering many items briefly beats covering few at length: 150 to 300
words for a conversation reply, shorter for a short question.

Re-check the list, then save with `file_editor` (`command`, `path`, `file_text`)
and `finish`.
