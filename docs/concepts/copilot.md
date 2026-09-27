# How the copilot works

The copilot answers a research question with the analysis operations of
CandyConc. A language model decides which operations to run. CandyConc runs
them on your corpus and records each result as an evidence item. For an
analysis question, a separate model call then writes the answer from these
evidence items. Before you see the answer, CandyConc resolves its citations,
compares its numbers and quotations with the evidence, and adds a record of
the analyses. Everything else in CandyConc works without the copilot.

## When the copilot runs

The copilot is off until a model endpoint is set, in
**Settings > Model connection** or with the setting `COPILOT_ENDPOINT`. An
installed CandyConc has no endpoint preset. Without one, the copilot panel
shows **No language model set up**, and a question sent over the HTTP API
returns the status 424 with the code `copilot_not_configured`.
[Connect a language model](../guides/copilot/connect-a-model.md) describes
the setup.

A question starts when you send it in the copilot panel. The interface posts
it to `/api/v1/chat/stream` and receives the progress and the answer as
server-sent events. For an endpoint on the same computer (`localhost` or
`127.0.0.1`), CandyConc first asks the model server for its list of loaded
models. If the server does not answer or does not list the configured model,
the question ends with an error before any work starts. The copilot sends
requests to the model endpoint only while it works on a question that you
sent.

## The language of a question

CandyConc chooses English or German once for each question, in this order:

1. The language detected from the wording of the question.
2. The interface language sent in `session.locale` in the UI context,
   when the wording does not identify a language.
3. The language selected from the request's `Accept-Language` header.
4. German when none of these provides a supported language.

A German question in an English interface therefore gets a German answer.
Corpus quotations, search expressions, and metadata values keep their own
language. The corpus language and its annotation pipeline remain the ones
chosen at import, see [Languages and annotation](languages-and-annotation.md).

For an English question, the routing rules map English analysis phrases to
the German cue vocabulary used to choose recipes, contracts, and tools.
Quoted search terms are excluded from cue substitution. The model receives
the question in its original language. The synthesis is instructed to answer in
English with comma grouping and a decimal point, for example `174,284` and
`1,592.3`, and the number check reads that format.

Answers written from fixed templates, evidence package labels, recovery
messages, experiments, the method card, and the evidence appendix follow
the answer language. This also applies to notes about missing evidence,
verification, spelling, and unmet recipe requirements. Interface controls
and tool cards follow the interface language. Internal instructions to the
model still include German text, and the API keeps its identifiers,
including the stage values `Vorlauf`, `Werkzeuge`, and `Antwort`.

## What happens to a question

```{mermaid}
flowchart TB
  question["Your question<br/>and the interface context"]
  prep["Preparation<br/>analysis recipe and analysis contract"]
  plan["Model plans<br/>the next tool calls"]
  tools["CandyConc runs the tools<br/>and records evidence items"]
  submit["Model submits<br/>its findings"]
  draft["Model writes a draft<br/>without tools"]
  synth["Synthesis<br/>fresh model call with evidence and draft"]
  direct["Answer written by CandyConc<br/>size and lookup questions"]
  finish["CandyConc finishes the answer<br/>references, checks, appendices"]
  answer["Answer with evidence chips"]

  question --> prep --> plan
  plan -- "tool calls" --> tools
  tools -- "results with evidence IDs" --> plan
  plan --> submit --> draft --> synth --> finish --> answer
  prep -. "size question" .-> direct
  tools -. "lookup complete" .-> direct
  direct --> finish
```

The diagram shows these steps:

- CandyConc prepares the question: it chooses an analysis recipe and sets up
  an analysis contract.
- The model plans tool calls. CandyConc runs them, records each result as an
  evidence item, and returns the results to the model, which plans the next
  calls. This loop is the tool phase.
- The model ends the tool phase by submitting its findings. It then writes a
  draft without tools.
- A fresh model call, the synthesis, writes the answer from the evidence
  items and the draft.
- A question about the size of the corpus, and a lookup question whose
  required evidence is complete, get an answer that CandyConc writes from the
  corpus description or the tool values, without a model writing the text.
- Before the answer is shown, CandyConc finishes it without a model, as
  described in
  [What CandyConc checks and adds without a model](#what-candyconc-checks-and-adds-without-a-model).

The interface shows the current stage of this work. The HTTP API reports it
in the event `copilot.status`:

| Stage in the interface | `stage` in `copilot.status` | What happens |
| --- | --- | --- |
| **Preparation** | `Vorlauf` | CandyConc chooses the analysis recipe and sets up the analysis contract. The model plans the first tool calls. |
| **Tools** | `Werkzeuge` | CandyConc runs tool calls. The model reads the results and plans the next calls. |
| **Answer** | `Antwort` | The model writes the draft, the synthesis writes the answer, and CandyConc finishes it. |

### Preparation: analysis recipe and analysis contract

An analysis recipe is a predefined procedure for one kind of question. There
are eight: **Frequency**, **Usage (KWIC)**, **Association**, **Contrast**,
**Trend**, **Profile**, **Metadata & structure**, and **Exploration**.
Keyword rules choose the recipe when they are decisive. Otherwise one model
call classifies the question, and a question that fits no recipe continues
without one. A recipe adds a briefing to the instructions of the model, with
the steps, the pitfalls, and the form of the answer for its kind of analysis,
and it makes sure that its core tools are offered.

Some recipes need a property of the corpus. **Trend**, for example, needs a
date field. When the corpus description shows that the requirement is
missing, CandyConc answers at once with an explanation from the recipe,
without a model call and without tools.

The analysis contract states which kind of analysis the question asks for,
what the answer has to deliver, which evidence it requires, and which tools
may run. Keyword rules set it up where they can. Otherwise structured model
calls propose, review, and complete it. A contract can also turn an ambiguous
question into a clarification question, which then becomes the answer or is
added at its end. A question without a valid contract continues as described
in [Questions without an analysis contract](#questions-without-an-analysis-contract).

### The tool phase

In each round, the model receives its instructions, a description of the
corpus, the context of the interface, the question, the tool calls of the
question so far with their results, and the tools it may call. It answers
with tool calls. CandyConc checks each call against the parameter schema of
the tool and the permissions of the user, runs it in the server process on
the active corpus, and returns the result to the model. The calls of one
round run in parallel, except the calls that create document sets, which run
one after another. The next model call reads the results and plans the next
round.

At the autonomy level **Plan first**, the first round of tool calls waits
until you confirm it. At the default level **Read freely**, the calls run
without confirmation, because every tool offered to the copilot only reads.

### Which tools the model can call

The tools are the analysis operations of CandyConc, in these groups:

- searching and reading: concordance search with the exact hit count, hit
  counts with rates per million word tokens, a wider context around one hit, the
  text of a document, and a ranked search for documents
- statistics: frequency lists, collocations and collocation networks,
  dispersion, trends along a date field, keyness, n-grams, word sketches, and
  lexical diversity
- comparisons: collocations of two subcorpora, n-gram contrasts, and the
  variants of a paired corpus side by side
- meaning: semantic passage search and similar words
- scope: metadata values, subcorpora from metadata or a search, and saved
  subcorpora
- a search in the documentation of CandyConc
- one tool without an analysis, with which the model ends the tool phase

These rules decide which of the tools a question is offered:

- Only tools that belong to a function the interface shows as a regular
  feature are offered, as listed in the capability contract at
  `GET /api/v1/capabilities`. The tools for semantic clustering belong to a
  hidden function and are not offered.
- The corpus decides as well. Without a passage index, the semantic search
  tools are removed, and without a word similarity index, the tool for
  similar words. Tools that need dependency relations or paired documents
  refuse a call with the reason. After such a refusal, the tool is not
  offered again in the same question, unless the refusal names an argument
  value that works.
- Keyword rules and the analysis contract select the tools that fit the
  question. A question whose kind is unclear gets the full list.
- Tools that the permissions of the user do not allow are removed.
- The recipe adds its core tools, and the contract limits the calls to the
  tools it allows.

`GET /mcp/tools` lists the same tools with their parameters, see
[How CandyConc works](how-candyconc-works.md).

### The end of the tool phase

The model decides when the tool phase ends. It calls the tool for this
purpose and states which part of the question the evidence answers, which
evidence items support it, and what stays open. After that call, the model is
offered no more tools.

If the model tries to finish before the evidence that the contract requires
is there, CandyConc narrows the tools to the missing ones and asks once more.
Two limits guard against a tool phase that does not end: 200 tool rounds, and
240 steps per question (`CANDYCONC_MAX_COPILOT_STEPS`). When one of them is
reached, the model gets no more tools and writes its draft as it does after
its own submission.

### Draft and synthesis

After the submission, the model writes a draft answer in the same
conversation, without tools. The interface does not show the draft.

The synthesis then writes the answer in a fresh model call. This call
receives no tools and none of the earlier conversation. It receives the
question, the lines of the corpus description about source texts, the origin
of variants, and token attributes, the evidence items of the question as
text, and the draft. Its instructions ask it to keep the interpretations of
the draft where the evidence covers them, to check every number, quotation,
and assignment against the evidence, and to cite the evidence item of every
number and every corpus quotation with a reference such as
`{{ev:E_run_cqlf_query_2}}`.

If the synthesis returns no text, or text that drops most of a long draft,
CandyConc repeats the call, up to three attempts. If no attempt returns text,
CandyConc composes the answer from the evidence items without model text.

### Answers that CandyConc writes without a model

Some questions get an answer whose text no model writes:

- A question about the size of the corpus, such as the number of documents,
  is answered from the corpus description before any tool runs, as long as
  no subcorpus is active.
- A lookup question is answered from the tool values as soon as the evidence
  that its contract requires is there. A question counts as a lookup when it
  is at most 160 characters long, asks for no interpretation, and its
  contract asks for a lookup answer. The model still plans the tool calls for
  it.

### Questions without an analysis contract

When no valid analysis contract can be set up, the question continues without
one. The model then writes the answer at the end of the tool phase, without a
separate synthesis and without evidence chips. CandyConc resolves the
references in this answer. When tool evidence is available, it also checks
numbers against the tool results and your question. CandyConc asks the model
once to correct references to missing evidence items and unsupported numbers.
Numbers that still have no support are replaced by a
placeholder, and sentences with a placeholder are removed, as long as no more
than half of the sentences would go. Quotations that present themselves as
corpus lines and appear in no evidence line are removed together with their
sentence.

## Evidence items and evidence chips

Each tool call gets an ID before it runs, in the form `E_<tool>_<n>`, for
example `E_collocate_stats_1`. The number `<n>` is the position of the call
among the tool calls of the question, in the order in which the model
requested them, across all tools. An ID is valid only within its question.

The model sees the ID at the top of every tool result, together with the name
of the tool and the arguments of the call. The answer cites evidence with
references to these IDs. A reference with a field, such as
`{{ev:E_run_cqlf_query_2.total}}`, is replaced by the value from the evidence
item. In an answer from the synthesis, a reference without a field becomes an
evidence chip.

Before the synthesis starts, the interface receives the list of all evidence
items of the question with tool, arguments, and status. It shows each
reference as a button labeled **Evidence** with a number. Evidence items
are numbered in the order of their first citation in the answer. Every chip
for the same item keeps that number, so **Evidence 1** always opens the same
source within that answer. Pointing at a chip shows the arguments of the
call. A click on a chip does the following:

- For a concordance search or a hit count, it runs the query of that call in
  the concordance, in the corpus and the document set of the call, including
  a subcorpus that the copilot created during the question. The tool aliases
  `default` and `active` refer to the corpus selected in the interface.
- For every other tool, it scrolls to the card of that tool call in the
  message and highlights it.

Every tool call has its own card in the message, with the name of the tool,
its status, its parameters under **Show parameters**, and a view of its
result. The card receives the result as the tool computed it, before any
shortening for the model.

At the end of the answer, CandyConc lists the evidence lines of the cited
evidence items: up to eight items with up to six lines each, taken from the
rows and values of each item.

## What the model sees of your corpus

In every call of the tool phase, the model receives:

- its instructions, with the briefing of the recipe
- a description of the corpus with its size, token attributes, metadata
  fields, date fields, capabilities, and the active subcorpus
- the context of the interface, such as the current query, the filters, the
  number of hits, and the last actions
- the question
- the tool calls of the question so far, with their results

Tool results contain corpus text: concordance lines with their context,
document text, and metadata values.

A tool result reaches the model unchanged when its JSON has at most 12,000
characters, at most 20 rows, at most four clusters, and at most six entries
per table. A larger result reaches it as a compact view that is marked as
such and states the size of the full result. The view shows up to 200 rows
and states their total. For a concordance list, the rows are spread evenly
over the list. A ranked list keeps its top rows, and a comparison table with
two directions keeps the strongest rows of each direction. The character
limit of the view grows by 12,000 for every 20 rows. If the rows still do not
fit, the view shows as many as fit and states how many are left out. The full
result stays in the server for the evidence item and the tool card.

The concordance tool returns the exact number of hits separately from its
lines. When there are more hits than requested lines (50 by default, at most
1,000), it returns a random sample drawn over all hits, with a seed derived
from the query and the scope, so the same call draws the same lines. The
method card at the end of the answer states the hit count, the number of
lines, and the sample with its seed.

For trends with more than 60 periods, the copilot tool returns an evenly spaced selection that retains the first and last dated periods and any undated bucket, preserves the counts of the selected periods, and reports the full period count and a reduction warning.

The synthesis receives the evidence items as text: for each item a header
with ID, tool, arguments, and status, followed by its rows and values. In a
concordance item, each line appears with its source and position. When lines
are left out, the text says how many and gives the exact hit count. The text
has a limit of 300,000 characters. Beyond it, the text ends at the boundary
of an item and names the evidence items that are left out.

During a long tool phase, the working record of the question can outgrow the
context window of the model. CandyConc then shortens the oldest tool results
in the model's copy and, if that is not enough, has the model summarize the
oldest part of the record. These limits follow the context window of the
model, 173,312 tokens unless `CANDYCONC_MODEL_CONTEXT_TOKENS` sets another
value. The synthesis reads the evidence items, which this shortening leaves
unchanged.

[Data and privacy](data-and-privacy.md#what-the-copilot-sends) lists what the
copilot sends to the endpoint and what CandyConc masks before sending.

## Each question starts without the earlier ones

The interface sends only the current question. The server starts a new
session for every question and does not read the conversation identifier
that the interface sends along. Earlier questions, their answers, and their
evidence items do not reach the model. A follow-up such as "and in the other
period?" arrives without the question it refers to. The context of the
interface arrives with every question, with the current query, the filters,
and the last actions. Over the HTTP API, earlier messages in the `messages`
array of the request reach the model as history.

The answer appears as a whole when the question is finished. Until then, the
interface shows the progress of the work.

## What CandyConc checks and adds without a model

The tools run in the CandyConc server on your corpus. After the synthesis,
CandyConc handles the references, numbers, and quotations of the answer
without a model. These three steps are the grounding check of the answer.

**References.** A reference to an existing evidence item becomes a chip or
the value from the item. A reference to an ID that does not exist in the
question is removed, and the sentence around it stays.

**Numbers.** A line with a number of at least 10 that exactly one analysis
result of the question contains, and that has no chip yet, gets a chip of
that result at its end, up to eight such chips per answer. The synthesis may
compute values of its own, such as percentages or ratios, which appear in no
tool result. CandyConc does not change the numbers that the model wrote
itself, and the answer shows no difference between inserted and written
numbers. The evidence lines, the method card, and the tool cards give the
values to recompute them from.

**Quotations.** CandyConc looks up quotations of at least 12 characters
that the answer presents as corpus lines, for example with the chip of a
concordance search after them. It checks German quotation marks „…“ and,
in an English answer, also curly “…” and straight "…" quotation marks. It
searches the evidence lines, the rows that the synthesis received, and the
search terms. A quotation found in
none of them stays in the answer, because it can also be a wording that the
model proposes, and a note below the answer names up to three such
quotations.

**Appendices.** From the evidence items, CandyConc adds these sections to
the answer:

- the experiments: for each tool call, which tool ran with which parameters
  and what it found
- the method card: the query level (word form, lemma, or query), case
  folding, window, denominator with its scope, how many hits became lines,
  and the state of the index
- the evidence lines of the cited evidence items

Between the answer and the appendices, CandyConc adds at most two sentences
that complete the answer, for example about a part of the question for which
no analysis ran. Further sentences of this kind go to the **Notes** below the
answer.

## While the copilot works, and when it stops

During the work, the copilot panel shows the current stage, a bar with the
number of tool calls so far out of the step limit, a card for each tool call
as soon as its result arrives, and system notes, for example when CandyConc
repeats a call. The research trace lists the steps in plain words while they
run, with their queries and results. After the answer, a line below it names
the analysis recipe, the number of model calls, and the duration, and the
**Timeline** shows how long each stage took.

### Stopping a question

**Stop answer**, closing the copilot panel, and sending a new question each
stop the running question. The server then starts no further model call, tool
call, or repeated call. CandyConc does not interrupt a model call that is
already running and discards its result. The question ends without an
answer, and the tool cards that arrived stay in the message. A new question
from the same user also stops a question of that user that still runs on the
server, for example one from another browser tab.

### Time limits

- `COPILOT_TIMEOUT` limits one request to the model endpoint. Its default of
  8,000,000 seconds guards against a connection that hangs.
- `CANDYCONC_COPILOT_MAX_TIME_SEC` sets a time budget for a whole question.
  By default there is none, and a question runs until the model submits its
  findings or the round or step limit is reached.
- With a budget, the model gets no more tools once 55 percent of it has
  passed (40 percent for **Exploration**) and at least one round has run,
  and it writes its draft from the evidence collected so far. When the
  budget is used up during the tool phase, CandyConc composes the answer from
  the collected evidence without a further model call. If a single step still
  blocks 15 seconds after the end of the budget, the server stops waiting and
  delivers an answer from the results computed so far, with a note under
  **Notes**. Without any evidence, the question ends with the status
  `timeout`. With request timeouts enabled, a question budget also caps
  each model request at the budget minus 20 seconds, with a minimum of one
  second for this cap.
- The model call that chooses the recipe has its own limit of 300 seconds.
  When it runs out or fails, the question continues with the recipe from the
  keyword rules or without a recipe.

### When the model endpoint stops answering

If the endpoint does not answer before the question starts, the question
ends with an error, and nothing else happens. If it stops answering during
the question, for example because the model server restarts or unloads the
model, CandyConc keeps the evidence collected so far, waits, and repeats the
same call with pauses of 2 to 30 seconds. It allows up to eight consecutive
retries, resetting this count after a successful model call.
For an endpoint on the same computer, CandyConc also waits as long as the
server does not answer or lists no loaded model. Without a time budget, this
wait has no upper limit, and **Stop answer** ends it. CandyConc does not load
or switch models.

When recovery ends after a model failure and evidence is available,
CandyConc composes an answer from the collected evidence and sends it with
the status `partial` and the error. The interface displays this text with
**Partial answer**, keeps the tool cards, and adds a message explaining the
model failure. An error event followed by this answer does not discard the
answer or restart the question. If the stream ends with an error and no
answer, the interface shows the error with **Try again**.

### How long a question takes

A question proceeds through preparation, tool calls, and the answer stage.
The selected analysis and the number of tool rounds determine the work to
be done, while the configured model endpoint determines how quickly model
calls return. During synthesis, the answer stage remains active while the
model reads the collected evidence and writes its response. Follow the
stage and tool cards while waiting, then open **Timeline** to see the
duration of each stage for that question.

## Which models work

The copilot needs a model that can call tools, served over an
OpenAI-compatible chat completions interface (`/v1/chat/completions`) or
responses interface (`/v1/responses`). CandyConc does not ship, load, or
switch models. If the context window of your model is smaller than 173,312
tokens, set `CANDYCONC_MODEL_CONTEXT_TOKENS` to its size so that the working
record is shortened in time. The evidence text of the synthesis keeps its own
limit of 300,000 characters. How to connect a model on your computer or at a
provider is described in
[Connect a language model](../guides/copilot/connect-a-model.md). How to read
an answer and follow its evidence is described in
[Ask the copilot and check the answer](../guides/copilot/ask-and-check.md).
