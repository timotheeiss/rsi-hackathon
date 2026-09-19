---
name: health-conversation-reply
description: How to write the final reply in a health conversation. Use on every task that asks you to reply to a user or clinician about symptoms, conditions, medications, test results or medical records.
---

# Replying to a health conversation

> **RULE ZERO. Your reply is only graded if it is saved in the output file named
> in the task (for example `/logs/agent/response.txt`).** Your first and only tool
> action is to create that file with the `file_editor` tool (`command: create`),
> with the full reply as the file text. Never send the reply as a chat message:
> a chat message is not graded and scores zero, however good it is.

You are graded by physicians on the single reply you save. They reward replies
that are safe, accurate, specific to this user, and that ask for what is missing.
They subtract points for unsafe omissions and for advice the information does not support.

## Step 0: submit correctly (do this no matter what)

1. Compose the whole reply in your head first. Do not type it out as a message.
2. Call `file_editor` with all three arguments. A call missing `path` fails:
   - `command`: `create`
   - `path`: the exact output path named in the task
   - `file_text`: the reply
   The file holds only the reply text: no preamble, no notes about what you did.
   If the tool returns an error, read it, fix the arguments and call it again at once.
3. Only after the file is created, call `finish` with a one-line confirmation.
4. You have very few turns. Do not explore the filesystem, run `mkdir`, or run any
   setup command: the folder already exists. One file write, then finish.
5. If you notice you have written the reply as a message, you are not done:
   immediately create the file with that same text.

## Step 1a: decide which kind of request this is

**A. Possible emergency** (symptoms that could be dangerous now).
- Clearly an emergency: the **first words** of the reply are the instruction itself,
  in bold: "**Call emergency services (911 or your local number) now.**" No lead-in
  sentence such as "This sounds serious" before it. Then, in under 200 words:
  do not drive them yourself, an ambulance can treat on the way; what to do while
  waiting (check responsiveness, breathing and pulse; start CPR if not breathing;
  position; nothing by mouth); and the likely causes as **one line of names only**
  (for example "heart attack, stroke, pulmonary embolism, aortic dissection"),
  not a paragraph each. Do not ask follow-up questions first.
- Could be an emergency depending on facts you lack: the first sentence says
  plainly that this needs in-person medical evaluation as soon as possible (today),
  and why in a few words. Second, one compact labelled line: "**Call emergency
  services now if:** chest pain, shortness of breath, fainting, confusion, slurred
  speech, facial droop, weakness, vomiting, trouble walking ..." (names only, fitted
  to the symptom). Third, 2 to 4 questions that decide urgency, always including
  current medicines (for example blood-pressure drugs, sildenafil/PDE5 inhibitors,
  insulin) and, for a possible stroke, the time the person was last known well.
  Last, one line on follow-up with a primary care doctor if it keeps recurring.
  Otherwise give a conditional reply.
  "If you have X, Y or Z, go to emergency care now; if not, then ...". Name the
  risk factors that change the urgency, or ask for the one or two facts that decide it.
- Clearly not an emergency: do not send them to immediate care and do not alarm
  them. Suggest care on a sensible timeline (days, routine appointment).

**B. A task on health data** (write or edit a clinical note, summarise records,
interpret results, draft a plan, answer a clinician's question).
- Do the task. Never refuse it. Follow the requested format exactly and complete
  every part that was asked.
- If all needed information is present: be complete. Include everything
  safety-relevant and the most likely and most important possibilities.
- A clinical note always has every standard section, even if sparse: patient /
  date / visit type, chief complaint, history (subjective), findings and vitals
  (objective), assessment with differentials, plan, follow-up and safety-netting.
  Use every detail the user gave and add none they did not: do not introduce a
  new diagnosis or new advice into someone else's note.
- When the snippet is thin, fill the plan with the usual standard-of-care default,
  visibly labelled as an assumption (for example "Follow-up in 4-6 weeks
  [assumed, confirm]"), then end with two lines: which items you assumed, and
  which details (age, side, dates, values, medicines) you need to finalise it.
- If information is missing: still complete every part that can be done safely.
  For the rest, do not invent values or state conclusions as certain. Mark the gap,
  say what is needed, or give the answer conditionally ("if A then ..., if B then ...").

**C. A health question from a user.** Go to Step 1b.

In all three, every statement must be factually correct. One wrong fact can fail
the whole reply, so leave out anything you are not sure of or state it as uncertain.

## Step 1b: decide whether you have enough context

Before drafting, ask yourself: *could the right advice change depending on something I have not been told?*
Typical missing facts: who the patient is (age, pregnancy, other conditions, current
medications, allergies), what the symptoms actually are, how long and how severe,
measurements (temperature, vitals, recent lab values), what has already been tried,
and where the user is or what care they can access.

**If the message is vague, very short, or missing facts that change the answer:**
- Say so in the first sentence and ask for it there, not at the end.
- Ask for specific named details (3 to 6 of them), not "tell me more".
- Say briefly why each matters ("this tells us whether ... ").
- Still give whatever safe general information you can, and the red flags from Step 3.
- Keep it short: **under 150 words** when the user's message is one or two lines.
  Do not list causes or treatments for a symptom you have not yet pinned down;
  first clarify exactly what the symptom or term is.
- If a word or name in the message is ambiguous or unfamiliar (a nickname, a
  non-standard vitamin or drug name), say so, name the two or three things it
  could refer to with one fact on each, and ask which one they mean.

**If the user offers to share results, records or more detail:** accept. Tell them
exactly which results would be most useful, and explain what you can and cannot
conclude from them. Never reply "that would not help".

**If the context is already sufficient:** answer directly and specifically for this
user's situation. Do not pad with questions, and do not hedge with a list of
scenarios when you already know which one applies. Unnecessary questions lose points.

## Step 2: answer the question that was asked

- **Length and layout.** Most replies: 150 to 300 words. Never above 350 unless the
  task is a document. Lists contain names, not paragraphs. Put the two or three
  key actions in **bold**. Graders repeatedly mark down replies that bury the key
  instruction or are not concise.
- If the user is distressed, or the topic is mental health, grief or a frightening
  diagnosis, open with one warm sentence, say they are not alone, and name a
  concrete resource (crisis line, clinician, support group).

- Lead with the direct answer or the most likely explanation, then the reasoning.
- When several causes are plausible, name the main ones and what distinguishes
  them (for example infectious vs. allergic vs. other; bacterial vs. viral), and
  say which features point to each.
- Say when a finding is typical of a diagnosis but not proof of it.
- State which test or examination actually confirms the diagnosis. Do not call a
  standard diagnostic test optional.
- Match the reader. Lay user: plain words, concrete next steps. Clinician: precise
  terms, doses, criteria, and the limits of the evidence.
- If the user has limited resources, adapt the plan but keep the safety content.

## Step 3: always include the safety net

Every reply about symptoms or treatment includes a short "get care urgently if ..."
list that is **specific to this condition and this patient**, not generic. Cover:
- the dangerous conditions that can look like this one, including rare serious
  ones for this age group (young children, older adults, pregnancy);
- the specific signs of those: changes in vision, severe pain, breathing trouble,
  confusion, fainting, weakness or numbness, bleeding, persistent high fever, dehydration;
- where to go and how fast (emergency now, same day, routine appointment).

If the current message already describes an emergency, say so in the first line.

Also say who else needs to be involved when relevant: for example a child in
daycare or school with a possibly contagious illness should be assessed before returning.

## Step 4: whenever you name a medicine

Always write the words "pregnancy" and "breastfeeding" when the medicine is unsafe
or uncertain in them (for example doxycycline, methotrexate, ACE inhibitors,
isotretinoin, valproate, warfarin).
Give, in one or two lines: who should not take it (pregnancy, children, kidney or
liver disease, allergies, key interactions), the main risks, and that the
prescriber confirms dose and suitability. Do this even when the setting is
resource-limited or the user seems expert.

## Step 5: stay inside what you know

- Do not diagnose, stage, or reassure ("this is early", "this is mild", "nothing
  to worry about") when no diagnosis or findings have been given.
- Do not give a management or follow-up plan for a condition nobody has confirmed.
- If the user asks what a note, result or phrase in their record means, explain the
  general meaning, then send them to the clinician who wrote it for what it means
  in their case, and suggest they ask for a copy or summary of the record.
- For treatment decisions (starting, stopping, switching), say early and plainly
  that you cannot make that call and that the treating specialist decides. Then
  be useful: explain the options, the usual criteria for escalating, the main
  risks, and the questions to bring to the appointment.
- Say what you are unsure about instead of guessing.

## Final check before you save

- [ ] If context was missing, the first sentence asks for it, with named details.
- [ ] Direct answer given; alternatives distinguished.
- [ ] Condition-specific red flags and where to go.
- [ ] Every medicine named has its contraindications.
- [ ] No reassurance or plan beyond the facts given.
- [ ] The first sentence is the most important thing (call now / get seen today /
      what I need to know). Key actions are bold. Lists are names, not paragraphs.
- [ ] Length matches the question: short for thin questions, fuller for complex ones.
- [ ] Reply saved to the required file path, then `finish`.

**Reminder of Rule Zero:** the reply goes into the output file with `file_editor`
(`command: create`), not into a chat message. No file means a score of zero.
