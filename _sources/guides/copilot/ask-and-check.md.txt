# Ask the copilot and check the answer

Use the copilot to investigate a question, then follow its evidence back to
computed results and corpus passages.

## Set up the question

1. Select the corpus and, if needed, the subcorpus you want to investigate.
2. Open the **Copilot** with the button at the bottom of the window. If it
   shows **No language model set up**, follow
   [Connect a language model](connect-a-model.md).
3. In **Chat**, write a question that names the expression, the kind of
   analysis, and the scope. With the English sample corpus, try:

   > How often does the word form "freedom" occur in the selected corpus?
   > Show concordance examples and describe how the word is used.

4. Press **Enter** or click the send arrow. **Shift+Enter** adds a line break.
   Clicking one of the suggested questions sends it immediately.

For a comparison, name both groups and the metadata field that distinguishes
them. For a follow-up, repeat the expression and the scope you mean. Each
question receives the current interface context and starts a new model
session.

## Read the computed results

While the copilot works, the panel shows its stage and tool cards. Each card
names an operation and its status. A successful call adds its computed result.
For calls with arguments, **Show parameters** opens the query and other
settings used for that operation.

Use the results under **Computed evidence** to check counts, rankings, and
examples. Read the method card at the end of the answer for the search level,
scope, denominator, and the number of concordance lines read. Compare any
percentage or ratio in the prose with the tool values it uses.

Read **AI interpretation** as the explanation to assess against those
results. For a claim about usage, inspect the cited passages and decide
whether their contexts support it. Open **Notes** below the answer when it
appears to read additional information about the evidence and checks.

## Return to the evidence

Click a numbered **Evidence** chip beside a claim:

- A chip for a concordance search or hit count runs that query in **KWIC**,
  using the corpus and subcorpus recorded for the call. Read the matches in
  their surrounding text.
- A chip for another analysis scrolls to its tool card and highlights it.
  Check the displayed values and open **Show parameters** to inspect the
  analysis settings.

Within an answer, chips with the same number refer to the same evidence
item. Point at a chip to see the arguments of its tool call. The evidence
lines at the end of the answer provide a compact view of the cited results.

## Keep the checked analysis

After reopening a query from an evidence chip, open **Runs** in the copilot
panel. Expand its run record to check **Corpus**, **Scope**, and **Result**.
Use **Add note** to record what you checked, then press **Enter** to save the
note. Select the record's checkbox and click **JSON** or **CSV** to download
its recorded analysis details, including parameters, scope and result
references, and notes.

Keep the question and answer text alongside the checked evidence in your
research notes.

## Stop or try again

Click **Stop answer** to end the current question. Tool cards already
received remain in the message. If a question ends with an error and offers
**Try again**, that button sends the original question again.

[How the copilot works](../../concepts/copilot.md) explains the analysis
recipes, evidence items, answer checks, and recovery behaviour in detail.
