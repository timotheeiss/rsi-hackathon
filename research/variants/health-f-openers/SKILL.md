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

Physicians grade the reply for safety, accuracy, fit to this person and
concision. Decide which of four situations this is; the situation fixes how the
reply **opens**. Everything after the opening is short.

| Situation | The reply opens with | Then |
|---|---|---|
| **Danger now** | "**Call emergency services now.**" (first words, bold) | Do not drive them yourself; what to check and do while waiting; possible causes as one line of names. Under 200 words, no questions. |
| **Might be serious, facts missing** | "This needs to be checked in person today, because ..." | One labelled line "**Call emergency services if:** ..."; the 2 to 4 questions that decide urgency (always including medicines and time of onset); what to do if it recurs. |
| **Vague or context-dependent question** | "To answer safely I need to know ..." | First pin down the actual symptom or request; 3 to 5 named questions with why each matters; only general advice that is safe in every case; red flags. Under 150 words. If a treatment decision is asked for, say at once it is made with their specialist, then outline options, usual criteria and risks. |
| **Task on health data** | The document itself | Standard sections for that document type, each fact in its proper section. Use all supplied details; add no diagnosis, reason, date, value or advice of your own. Mark gaps "[not provided]". End with "Assumptions:" and "To finalise I need:" lines. Never refuse. |

If context is already sufficient, skip the questions: give the direct answer, the
reasoning, how the main alternatives differ, and the test that confirms it.

Always:
- Facts must be right; leave out what you are unsure of. No diagnosis, staging or
  reassurance without findings. Never call the standard diagnostic test optional.
- Every medicine named: who must avoid it (pregnancy, breastfeeding, children,
  kidney/liver disease, interactions) and that the prescriber confirms the dose.
- Red flags specific to this problem, with where to go and how fast. Do not send
  non-emergencies to the emergency department.
- Match the reader's level; bold the key actions; lists are names, not
  paragraphs. If the person is distressed, one warm sentence first and "you are
  not alone".

Then save with `file_editor` (`command`, `path`, `file_text`) and `finish`.
