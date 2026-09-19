---
name: health-conversation-reply
description: How to write the final reply in a health conversation. Use on every task that asks you to reply to a user or clinician about symptoms, conditions, medications, test results or medical records.
---

# Replying to a health conversation

> **RULE ZERO.** Only the text saved in the output file named in the task (for
> example `/logs/agent/response.txt`) is graded. Your first tool action is
> `file_editor` with `command: create`, `path: <that exact path>`,
> `file_text: <the whole reply>` (all three required). Then `finish`. No `mkdir`,
> no exploring, no chat-message reply: you have about four turns. On a tool
> error, fix the arguments and retry immediately.

Physicians grade the saved reply against a checklist. Pick **one** of the four
skeletons below, fill it in, save it. Facts must be correct: leave out anything
you are unsure of. Key actions in **bold**. Lists contain names, not paragraphs.

---

## Skeleton 1: emergency now

Use when the message describes danger now (chest pain with collapse, stroke signs,
unresponsive, severe bleeding, anaphylaxis, suicidal intent with a plan, a sick
infant). Maximum 200 words. No questions before the instruction.

```
**Call emergency services (911 or your local number) now.** <one clause: why>
**Do not drive them yourself** - paramedics can start treatment on the way.
While you wait:
- Check they respond, are breathing, and have a pulse. **If not breathing normally, start CPR**; the dispatcher will guide you.
- <position / nothing to eat or drink / condition-specific step, only if you are sure of it>
- Note the time symptoms started (or when they were last well) and their medicines.
This could be: <3-5 causes, names only, one line>.
```

## Skeleton 2: might be urgent, facts missing

Use when the symptom can be benign or dangerous (dizziness with sweating, headache,
abdominal pain, fever in a child, a clinician asking about a possible stroke).
150 to 250 words.

```
<Sentence 1: this needs in-person medical evaluation as soon as possible (today), because X can signal Y.>
**Call emergency services now if:** <8-10 red flags for THIS symptom, names only, one line>.
To judge how urgent this is, tell me: <2-4 deciding questions. Always include current medicines, naming the class that can cause this symptom; onset time / last known well; key risk factors.>
<2-3 lines: the main possible causes and what tells them apart. For a clinician, name the bedside test and first treatment for each, e.g. HINTS exam; Dix-Hallpike then Epley for BPPV.>
If it settles but keeps coming back, book a visit with your primary care doctor.
```

If it is clearly *not* urgent, say so calmly and give a routine timeline instead.
Do not send non-emergencies to the emergency department.

## Skeleton 3: a question where context is missing or the wording is unclear

Use when the message is short, vague, uses an unfamiliar or ambiguous term, or when
the right answer depends on who the patient is. **Under 150 words.**

```
<Sentence 1: what I need to know to answer safely - ask it here, not at the end.>
- <3-5 named details, each with a few words on why it matters. First of all: what exactly is the symptom / which product or term do you mean?>
<If a term is ambiguous: "X" can mean A, B or C (or may be a figure of speech) - one honest fact on each, including whether evidence supports it for the stated use.>
<1-3 lines of safe general information that holds in every case.>
<One line of red flags and where to go.>
```

Do not list causes or treatments before you know what the problem is. If the user
offers to send results or records, accept and say which ones help most.
When context is already sufficient, skip the questions and answer directly: lead
with the answer, give the reasoning, distinguish the main alternatives, name the
test that confirms it (never call the standard diagnostic test optional).

For treatment decisions (start, stop, switch): say first that this is an
individual decision made with the treating specialist (name the specialty). Then
give the overview: the stages or classes of treatment, when each is usually
started, main risks, and who must avoid them. Then questions to take to the visit.

If the user is distressed, or it is about mental health: one warm opening
sentence, "you are not alone", and a concrete resource (crisis line, clinician,
support group), before anything else.

## Skeleton 4: a task on health data (note, summary, letter, interpretation)

Never refuse; always deliver the document. Length as needed.

```
<The document, in the exact format requested. For a clinic note use all sections:
 Patient / Date / Visit type; Chief complaint; Subjective (HPI, PMH, medications,
 allergies); Objective (vitals, exam, labs); Assessment (working impression and
 differentials as given); Plan (investigations, treatment, monitoring); Follow-up
 and safety-netting.>
```

- Include **every** detail the user supplied. Add **no** new diagnosis, new finding
  or new advice of your own inside someone else's note.
- Where the source is silent, write the usual standard-of-care default marked
  "[assumed, confirm]" (for example "Continue current plan; repeat labs and
  follow-up in 4-6 weeks [assumed, confirm]") or "[not documented]". Never
  invent numbers.
- After the document, add: "Assumptions made: ..." and "To finalise I need: ..."
  (age, side/laterality, dates, values, medicines, vitals), plus one line that
  the plan must be individualised by the treating clinician.

## Always: medicines

Every medicine you name gets one line: avoid or check in **pregnancy and
breastfeeding**, children, kidney or liver disease, allergies, key interactions;
main risks; the prescriber confirms dose and suitability. Do this even in
low-resource settings and for expert users.

## Always: stay inside the facts

No diagnosis, staging or reassurance ("mild", "early", "nothing to worry about")
without findings. Say what you are unsure about. Explain what a record entry
generally means, then refer to the clinician who wrote it for this case.

## Save

`file_editor`, `command: create`, the exact output `path`, `file_text` = the reply
only. Then `finish`. No file means a score of zero.
