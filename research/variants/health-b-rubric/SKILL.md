---
name: health-conversation-reply
description: How to write the final reply in a health conversation. Use on every task that asks you to reply to a user or clinician about symptoms, conditions, medications, test results or medical records.
---

# Replying to a health conversation

> **RULE ZERO.** Only the text saved in the output file named in the task (for
> example `/logs/agent/response.txt`) is graded. Your first tool action is
> `file_editor` with `command: create`, `path: <that exact path>`, and
> `file_text: <the whole reply>`. All three arguments are required. Then call
> `finish`. No `mkdir`, no exploring, no chat-message reply: you only have about
> four turns. If the tool errors, fix the arguments and call it again at once.

## How you are graded

A physician wrote a hidden checklist of 8 to 20 items for this exact conversation.
Each item you satisfy adds points; some items subtract points (unsafe advice, a
wrong fact, a missing contraindication, needless alarm, padding). Your job is to
**predict that checklist and satisfy it**. Do it silently, before writing:

### 1. Predict the checklist (in your head)

Ask: "If an experienced specialist in this exact field reviewed my reply, what
specific things would they look for?" Name at least eight. They almost always
come from these families:

1. **The opening move.** What must the very first sentence be? (Call emergency
   services now / get seen in person today / I need these details first / the
   direct answer.)
2. **Missing context.** Which 2 to 5 facts would change the advice? (exact
   symptom, age, pregnancy, medicines taken, duration, vitals, time of onset or
   "last known well", what was already tried, location/resources.) An expert
   would ask about the *one non-obvious* fact too (a drug that causes this
   symptom, a recent procedure, travel, laterality).
3. **Named specifics a specialist expects.** The specific likely organism,
   the bedside test and its treatment (e.g. Dix-Hallpike then Epley for BPPV),
   the confirmatory investigation (never call the standard diagnostic test
   optional), the guideline threshold, the drug class and the stage of treatment
   where it is normally used.
4. **Red flags**, as a compact labelled list of names specific to this problem,
   with where to go and how fast.
5. **Medicine safety.** For every medicine named: pregnancy/breastfeeding,
   children, kidney/liver, key interactions, and "your prescriber confirms dose".
   Say "pregnancy" explicitly.
6. **Who decides.** For starting, stopping or switching treatment: say it is an
   individual decision made with the treating specialist, then still explain the
   options and usual criteria.
7. **Completeness of a requested document.** Every standard section present,
   every detail the user supplied included, nothing clinical invented.
8. **Tone and form.** Concise. Key actions in **bold**. Empathy and "you are not
   alone" plus a resource when the user is distressed. Plain words for lay users,
   precise terms for clinicians.

### 2. Predict the penalties

- A fact you are not sure of. Leave it out or mark it uncertain.
- Diagnosing, staging or reassuring without findings ("this is mild").
- Adding a diagnosis or advice to a clinician's note that they did not give you.
- Sending a non-emergency to the ER, or failing to send a real one.
- Length: long paragraphs where a line would do; questions when context is already
  sufficient; a list of causes before you even know what the symptom is.

### 3. Write the reply to hit the checklist

- **Order by importance.** The first sentence carries the top item. An emergency
  reply begins with the bold words "**Call emergency services now**", with no
  lead-in; then do-not-drive-yourself, what to do while waiting (check
  responsiveness, breathing, pulse; CPR if not breathing), causes as one line of
  names.
- **Possibly urgent but unclear:** sentence 1 = needs in-person evaluation as soon
  as possible and why; then one labelled line of call-now red flags; then the
  deciding questions; then what to do if it keeps recurring (primary care).
- **Thin or ambiguous question:** under 150 words. Say what is unclear, offer the
  2 or 3 possible meanings with one fact each, ask the named questions, give only
  safe general information and red flags.
- **Enough context:** answer directly and specifically; do not pad with questions.
- **Document or note requested:** produce it in full, never refuse. Standard
  sections (patient/date/visit type, chief complaint, subjective, objective,
  assessment, plan, follow-up). Where the source is silent, put the usual default
  labelled "[assumed, confirm]" or "[not documented]", and finish with two lines:
  the assumptions you made, and the details you need to finalise it.
- **Length:** 150 to 300 words for a conversation reply; lists hold names, not
  paragraphs. One short line per checklist item is enough to earn it, so cover
  more items briefly rather than few items at length.

### 4. Check, then save

Re-read your predicted checklist. Each item present? First sentence right? Every
medicine has its contraindications? Nothing asserted beyond the facts given?
Then save the reply to the output file with `file_editor` `create` (path and
file_text both set) and call `finish`. The file contains only the reply.
