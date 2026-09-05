<!-- Artifact: https://claude.ai/code/artifact/87469ec6-9303-4bc7-823f-ba180a18f502 -->
<!-- Redeploy to that URL rather than publishing a second one. Task 21 re-reads
     this file and the diagrams against the built system and updates the same link. -->

# Talk track — onboarding a business client

Narration for the three diagrams in [`docs/DESIGN-DIAGRAMS.md`](docs/DESIGN-DIAGRAMS.md).
Written to be read aloud on a call, and to still make sense to someone who
reads it afterwards with nobody to ask.

---

## The problem

Opening a commercial account is not one form and one ID. It is five or six
documents from different sources, several people whose identities have to be
verified, and a compliance review that takes days — because the analyst is
waiting on a registry, a client callback, or a colleague. Meanwhile a core
banking system that was built in a different decade has to be told to create
the account, and it answers on its own schedule.

Most banks automate the easy middle of this and leave the ends alone. The
extraction gets a script, the review gets a queue, and the two are stitched
together with a status table, a nightly job, and someone who knows which rows
to look at when a case gets stuck. That works until a document arrives late, a
call times out, or a machine restarts — and then the recovery is manual,
because nothing in the system knows what "half done" means.

---

## Diagram 1 — how the process is put together

**What to say.** This is the whole process, and it reads top to bottom the way
the business already describes it: collect, extract, review, open, wait,
deliver, notify. Someone in compliance can look at this and recognise their own
procedure. That matters more than it sounds, because it means the automation is
auditable by the people who own the risk.

The AI is one step. Step two. It is drawn as a separate box because it *is* a
separate unit — it gets a typed request and returns a typed result, and if it
does something strange, the strangeness is confined to that box. When someone
asks "how do you control the AI," this diagram is the answer: not with a
prompt, with a boundary.

Two of these steps are waits. Step three waits for the analyst; step five waits
for the core banking system. Neither one costs anything while it waits. Nothing
is polling, no cron job is checking a table, and no thread is held open. If the
machine running this dies mid-review, the review is unaffected — it resumes
where it was, whether that is minutes or a fortnight later.

Point at the reject arrow. It goes back to step one, not step two. When the
analyst says "you're missing the EIN letter," the specialist drops the file in
and the whole collection step runs again. The next attempt starts from a clean
slate rather than resuming a confused conversation with the model.

**The question this anticipates:** *"So what happens when the AI gets it
wrong?"* — A human sees every field before an account is opened, the analyst's
corrections are recorded separately from what the model produced, and the
process cannot reach step four without an explicit approval. Not a timeout, not
a default. An approval.

---

## Diagram 2 — the failure that matters

**What to say.** This is the one I would build the whole system around.

The process asks the core banking system to open an account, and after five
seconds it gives up waiting. Now: has the account been created or not? The
honest answer is *nobody knows*. The request did not stop when we stopped
listening. The bank's system is very possibly still working on it.

Most systems treat "no answer" as "did not happen" and retry. That opens a
second account. For a business client that is not a bug you patch next sprint —
it is a regulatory conversation, a remediation, and a customer who has to be
told.

So the interesting part is not the timeout. It is the retry. The request
carries a key derived from the application itself, which means it is the same
key on every attempt — that is what idempotency means here, and it is why the
second request is recognisable as the same request rather than a new one. The
bank's system looks the key up, finds the account it already made, and answers
"duplicate — here is the original." One account. The process carries on with
the right number, and nobody downstream ever learns anything went wrong.

Then the client ID comes back separately, whenever it comes back. That is the
second wait, and it is why a core system that answers in seconds and one that
answers in three days need no different handling here.

**The question this anticipates:** *"Couldn't you just make the timeout
longer?"* — You can make it longer, and you will still have this problem, just
more rarely and at a worse moment. The timeout is not the thing that has to be
right. The retry is.

---

## Diagram 3 — inside the AI step

**What to say.** Here is the loop, and there is exactly one thing in it that
leaves the process: asking the model. That call is retried on its own terms,
timed, and recorded. Everything else in this picture is bookkeeping that cannot
fail halfway.

The loop exists for a specific reason. The tax ID appears in the EIN letter and
again on the W-9. If the EIN letter scanned badly, the right move is to go and
look at the W-9 — and that is a judgement the model makes, not a fallback we
wrote in advance. That is the honest case for putting a model here at all: not
that it reads faster, but that it decides what to read next.

When it asks for a document, what gets remembered is the *name* of the
document. The paperwork itself is fetched fresh by the part of the system
allowed to touch storage. The orchestrator never holds a scan of anyone's
passport.

And when a field genuinely is not in any document — say one beneficial owner's
date of birth — the loop does not guess and does not fail. It escalates: this
field, these documents searched, over to a human. An escalation here is a
normal outcome with a normal shape, not an error to be caught somewhere.

**The question this anticipates:** *"What stops it looping forever?"* — A fixed
ceiling on attempts. When it runs out, it escalates with whatever it has,
which is the same path as any other unfindable field.

---

## What this buys the bank

**An account is opened exactly once.** Not "usually once, and we have a report
that finds the duplicates." The idempotency key makes the retry safe by
construction, so the failure that produces two accounts cannot happen — and
the proof is a response that says "duplicate," which you can point at.

**An auditable record of what the AI produced versus what the human changed.**
The model's output is kept; the analyst's corrections are applied on top as a
separate, attributed layer. When a regulator asks which of these fields a
machine filled in and which a person did, that question has an answer, per
field, without anyone reconstructing it from logs.

**Processes that survive multi-day waits without a status table.** No cron job
scanning for stalled cases, no "in progress" column that drifts out of sync
with reality, no nightly job to nudge the stuck ones. The waiting *is* the
process. It survives deploys and restarts, and a case that has been open for
nine days is in the same shape as one opened nine minutes ago.

---

## What we cut, and why

Stating these plainly, because a design that has obviously considered them
reads better than one that has not.

**Encryption of the data in transit through the orchestrator.** This is the
strongest candidate for the next increment, and the sharpest version of the
question is already answered: the documents never enter the orchestrator at
all, only references to them. Turning on encryption would also make the
operational view unreadable without extra tooling, which is a real cost during
a demo and a manageable one in production.

**Chasing documents over weeks.** A real deployment would start the process
when the application is created and then wait, possibly for weeks, for
paperwork to trickle in — chasing the client on a schedule. It is a second
long-running wait with its own story, and it would compete with the account
opening one for attention. Partly covered already: because rejection re-runs
collection, documents added late do flow through.

**Reading document images directly.** Working from the text layer is more
reliable, and image handling would add a failure mode that teaches nothing
about the design. It attaches at exactly one point if wanted.
