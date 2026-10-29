# We Asked an AI to Rewrite Its Own Instructions. It Mostly Learned to Be Cheaper.

*Draft, 2026-10-29. All runs are complete.*

Every coding agent ships with a system prompt, and almost nobody tunes it for their own codebase. The model vendors tune the model. The harness authors tune the generic prompt. The part that knows about *your* repository (which test runner works, where the logic lives, what a good fix looks like here) is usually empty.

GEPA is a method for filling in that empty part automatically. We ran it on eight models against our Zulip coding benchmark to answer one question: does an automatically written, repository-specific prompt make a coding agent better? The short answer is that it did not make any model solve significantly more tasks, but it made several models much cheaper. When we told GEPA to care about cost, GPT-5.6 Luna got 42% cheaper per task with no loss in accuracy we could detect. GPT-5.6 Sol also got 42% cheaper and Haiku 5.5 got 70% cheaper, both with a small accuracy loss we could not rule out.

The rest of this post explains what GEPA does, shows the actual prompts it wrote, and walks through why the cheaper prompts are cheaper.

## The onboarding note

Here's an analogy that we will carry through the rest of this post.

When a new engineer joins a team, someone usually writes them an onboarding note. "There's no local database, so don't try to run the full test suite. Backend logic is in `zerver/lib/`. When you change a function, grep for its callers." A good onboarding note saves the new hire a week of stumbling. A bad one makes them do pointless busywork.

The agent's appended system prompt is exactly that note. Our benchmark harness (pi) gives every model the same generic system prompt and lets us append extra text. The **baseline** in every experiment below appends nothing. The new hire gets no note at all.

GEPA (from the paper *GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning*, arXiv 2507.19457) writes the note by watching the new hire work. The loop runs like this:

1. Run the agent with the current note on a small batch of tasks (6 tasks, 3 attempts each).
2. Give a stronger model (the **reflector**, Claude Opus 5.5 in our runs) the full work logs: every command the agent ran, the patch it produced, which hidden tests failed and why. The reflector also sees the reference fix and the hidden test, which the agent never sees.
3. The reflector rewrites the note to address what went wrong.
4. If the new note scores better on that batch, it is scored on all 20 validation tasks and kept in a pool of candidate notes.

GEPA keeps a pool rather than a single best note. A note that is the best on *any* individual task stays in the pool (the paper calls this Pareto selection), so a note that is great at frontend tasks is not thrown away just because another note is better on average. We gave each run a budget of 240 agent runs, which produced 5 to 8 candidate notes per model.

The important detail is what GEPA optimizes. We ran two setups. In the **accuracy focus** setup the score is accuracy (did the patch pass the hidden test, with partial credit for passing some of the tests). In the **cost focus** setup the score is accuracy minus a penalty for cost:

score = accuracy − 0.1 × (cost of this run ÷ cost of the baseline on the same task)

The penalty is capped, and its weight is small on purpose. Halving the cost of every task is worth 0.05, i.e. one twentieth of a solved task. Solving tasks stays the main objective, and cost breaks ties. We also told the reflector about the objective in plain words, and it sees the dollar cost of every run next to the baseline's cost. In onboarding-note terms, the manager writing the note now sees the new hire's expense report as well as their code reviews.

## How we measured it

GEPA only ever sees 20 *validation* tasks. To check that a note helps in general and not just on the tasks it was tuned on, we ran every final note on 30 *held-out* tasks that GEPA never saw, 3 times each (90 runs per note), alongside the baseline on the same tasks. All tasks are real Zulip bug fixes and features, and each is graded by hidden tests that must fail before the patch and pass after it. We picked hard tasks on purpose (earlier board runs solved 0 to 4 out of 5 models on each).

Two numbers matter in the tables below. The **resolve rate** is the fraction of runs whose patch passed the hidden tests. The **cost ratio** is how much a run costs with the new note divided by what it costs with the baseline, averaged over the 30 tasks (a geometric mean, so a ratio of 0.5 means "half the cost on a typical task"). The bracketed ranges are 95% confidence intervals from resampling tasks. The p-values come from a paired test that asks how often a difference this large would appear if the note did nothing.

We also ran an earlier, simpler version of the accuracy focus setup on five of the models (the reflector did not see the reference fixes, and GEPA scored each task from a single run). It led to the same conclusions, so this post reports only the later version; both are in our results file.

One more piece of context explains why we needed 3 samples per task. When we ran the *same* prompt twice, about 22% of per-task outcomes flipped. A difference of one or two solved tasks out of 30 is noise.

## Finding one: no note made any model solve significantly more tasks

On the validation tasks, GEPA always found a better note. The validation score went up by 0.06 to 0.25 for every model. On the held-out tasks, those gains disappeared. No model's resolve rate changed by an amount we could distinguish from noise (every p-value is 0.26 or higher).

We think this is the familiar problem of picking a winner on a small test set. With only 20 validation tasks and outcomes that flip 22% of the time, the note that looks best on validation is partly the note that got lucky. The reflector also saw the reference fixes for those 20 tasks, so some notes contain rules that only matter for one specific validation task (more on that below).

We also had a hypothesis going in, that smaller models would gain more from a good note than frontier models. The data do not support it for accuracy. The three smallest models (Qwen3.6 27B, Muse Glimmer 30B and Gemma 4 31B) moved by +1.1, +3.4 and −3.4 points with their accuracy-focus notes, and none of these changes is significant.

## Finding two: the notes made several models cheaper, and asking for it doubled the saving

Cost is a different story. Even when GEPA optimized only for accuracy, the accuracy-focus notes cut the held-out cost of Haiku 5.5 to 0.78x (p = 0.04), gpt-oss-120b to 0.80x (p = 0.04) and Qwen3.6 27B to 0.77x (p < 0.01). The cost-focus notes went much further. Luna dropped to 0.58x with every one of the 30 tasks cheaper but one, Sol dropped to 0.58x with all 30 tasks cheaper, and Haiku 5.5 dropped to 0.30x with all 30 tasks cheaper.

For Luna and Sol, we ran both setups, so we can separate the two effects. For both models the accuracy-focus note saved 14% (0.86x), and the cost-focus note saved 42% (0.58x). Most of the saving comes from telling GEPA that cost matters, not from GEPA alone.

The accuracy side of the cost-focus notes differs between models. For Luna, the resolve rate went *up* slightly (0.678 to 0.711), and the confidence interval shows any loss is smaller than 2.2 percentage points. That clears the bar we set beforehand, which was proving that any loss is smaller than 10 points. For Haiku 5.5, the resolve rate went down from 0.823 to 0.767 over 6 samples per task. The drop is not significant (p = 0.26), but the interval reaches down to a 15-point loss, so we cannot claim the note is as accurate as the baseline. Sol is in the same position, with 0.789 down to 0.744 (p = 0.59) and an interval that reaches a 16-point loss.

## What actually changed in the notes

The easiest way to see what GEPA does is to read the notes. Both Luna notes are about 660 words, and both open with the same discovery, which every model's GEPA run found in some form: the sandbox has no virtualenv, no node_modules and no database, so the Zulip test runners cannot run. The baseline agent spends turns trying anyway. The difference between the two notes is what they tell the agent to do instead.

The accuracy-focus note tells Luna to build its own checks:

> **Verify (mandatory before finishing).** You cannot run the project test suites, so you must check your logic another way. [...] TypeScript: copy the pure logic you changed (string slicing, regexes, index/caret arithmetic, sorting/partitioning) into a temp .js file, run it with `node`, and assert the outputs for the brief's examples and the existing tests' cases.

> Update or add tests in the existing test files that match the brief's examples.

The cost-focus note tells Luna to read precisely, batch its searches and stop:

> Locate the code fast. Put independent `rg -n ... | head -20` searches in a single turn. Read only the relevant function with `sed -n 'A,Bp'` (about 80–120 lines at most per read). Never read whole large files, and never re-read a range you already have. Skip git history [...]

> Don't write or edit tests unless the brief asks for them.

> Finish with a single command: `python3 -m py_compile <changed .py files>; git diff`. Then trace each example from the brief [...] by hand. [...] Once the code does what the brief says, don't keep weighing alternatives, polishing or refactoring.

We counted what the agent actually did in the 90 held-out runs of each note. The numbers are means per run.

| What the agent did (per run) | Baseline | Accuracy focus | Cost focus |
|---|---|---|---|
| Model turns, relative to baseline | 1.00 | 0.86 | 0.59 |
| Shell commands | 27.7 | 24.4 | 18.8 |
| Attempts to run the test suite, pip, tsc, etc. (always fail) | 4.4 | 0.3 | 0.1 |
| Scratch-script checks (`python3 -c`, `node -e`) | 2.3 | 2.6 | 0.5 |
| Edits to test files | 1.4 | 2.8 | 0 |
| Whole-file reads | 1.9 | 1.3 | 0.02 |
| Ranged file reads | 22.9 | 22.2 | 22.9 |
| Code searches | 13.8 | 12.8 | 13.6 |
| Largest prompt in the run (tokens) | 80K | 77K | 63K |

The table tells a clean story. Both notes stop the failed toolchain attempts, which is most of the accuracy-focus saving. The accuracy-focus note then *adds* work, doubling the edits to test files. The hidden tests grade the patch, so the agent's own tests never change the score; they only cost tokens. The cost-focus note removes that extra work, nearly eliminates whole-file reads, and batches searches into fewer turns. Notice what it does *not* cut. The number of searches and ranged reads is the same as the baseline's, so the agent still explores the code as much as before. It just does so in 41% fewer round trips, and each round trip re-sends a smaller context.

In onboarding-note terms, the accuracy-focus note says "you can't run the tests, so write your own scaffolding and test everything by hand." The cost-focus note says "you can't run the tests, so read carefully, trace the examples in your head, and ship." For Luna, the second note was strictly better.

## Haiku 5.5 got the same advice and paid for it on three tasks

The Haiku 5.5 notes follow the same pattern. The accuracy-focus note is 1,137 words of careful engineering advice, and the cost-focus note is 420 words that read like a compressed version of it. The cost-focus note ends with this line:

> When the diff covers every requirement and you've re-read it once, stop.

The behavior changed the same way it did for Luna, only more so.

| What the agent did (per run) | Baseline | Accuracy focus | Cost focus |
|---|---|---|---|
| Model turns | 43.1 | 29.2 | 22.5 |
| Shell commands | 36.7 | 22.8 | 17.9 |
| Attempts to run the test suite, pip, tsc, etc. | 10.1 | 0.8 | 0.1 |
| Scratch-script checks | 4.4 | 2.3 | 1.3 |
| Code searches | 21.8 | 15.7 | 12.4 |
| Largest prompt in the run (tokens) | 99K | 91K | 58K |

The last row matters more for Haiku 5.5 than for any other model, because Anthropic charges five times the per-token price once a single request's prompt exceeds 100K tokens. With the baseline, 21% of requests crossed that line. With the cost-focus note, 1% did. That is why Haiku's saving (0.30x) is so much larger than Luna's.

Unlike Luna, Haiku 5.5 cut its *searches* too, by 43%. The accuracy loss is concentrated in 3 of the 30 tasks, which the baseline solved in 17 of 18 runs and the cost-focus note solved in only 5 of 18. We read all of the failed patches, and all three failures share one cause. The agent changed the right function but missed a constraint that lived *outside* that function.

- **A second caller.** The task asked for alert words to be highlighted inside topic links. The fix renames a template parameter, and two files render that template. Every baseline run updated both files. The four failing cost-focus runs updated only one; the two passing runs updated both.
- **A test harness rule.** The task added a Ctrl+P print shortcut. The failing runs routed the new key through a code path that looks up the focused element with a jQuery selector that Zulip's test stubs do not allow, so the hidden test crashed.
- **An exact-equality test.** The task marked deactivated users in the sidebar. The failing runs added a new `is_deactivated` field to *every* user's row object, and an existing test compares those objects field for field.

The detail that surprised us is that the cost-focus agent *looked at* the relevant file (the second caller, the test file) in every one of its 18 runs on these tasks, just like the baseline. It saw the constraint and did not act on it. The baseline spent 58 turns per run on these three tasks, compared with 30 for the cost-focus note, and the extra turns went into following up on what it found.

The Haiku accuracy-focus note contains the warnings that would have prevented two of these failures:

> Update every caller of any function whose signature or return type you change (grep the whole repo [...]).

> Frontend tests load modules with `zrequire` and replace dependencies with `mock_esm(...)`. [...] If you add a call to another module, or run an existing call in more cases, tests that mock that module can crash with "x is not a function".

The cost-focus note dropped both while compressing 1,137 words to 420. The cost penalty rewards a shorter note (the note itself is re-sent on every turn), and on the 20 validation tasks those warnings did not happen to pay for themselves. Luna's cost-focus note kept an equivalent warning ("When you extend a function [...] go through EVERY branch") and lost nothing. We cannot tell from 30 tasks whether the difference is the model or the note, but the mechanism is clear. A cost objective will remove any advice whose benefit does not show up on the validation set, including advice that protects against rare but real failures.

We also want to flag a smaller issue with both setups. Because the reflector sees the reference fixes, some notes include rules that only make sense for one validation task, e.g. Luna's cost-focus note warns about Zulip's `$t` translation helper translating a string twice, and names `message_lists.current` as the way to read app state. These rules did no harm on the held-out tasks, but they are memorized answers rather than general advice, and they are part of why validation gains do not carry over.

## Results for every model

Each table compares the baseline (no note) with the best note from each setup on the 30 held-out tasks. Each task ran 3 times (6 times for the Haiku 5.5 baseline and cost focus). Cost is dollars per agent run at list prices; for open-weight models it is a public hosting provider's per-token price, not our own GPU cost. Haiku 5.5 cost includes the long-prompt price tier.

### GPT-5.6 Luna

| Note | Resolve rate | Change vs baseline [95% CI] | Cost per run | Cost ratio | Turns ratio |
|---|---|---|---|---|---|
| Baseline | 0.678 | | $0.083 | 1.00 | 1.00 |
| Accuracy focus | 0.644 | −0.033 [−0.144, +0.067] | $0.078 | 0.86 (p = 0.05) | 0.84 |
| **Cost focus** | **0.711** | **+0.033 [−0.022, +0.100]** | **$0.051** | **0.58 (p < 0.001)** | **0.60** |

### Claude Haiku 5.5

| Note | Resolve rate | Change vs baseline [95% CI] | Cost per run | Cost ratio | Turns ratio |
|---|---|---|---|---|---|
| Baseline | 0.811 (6 samples: 0.823) | | $0.132 (6 samples: $0.151) | 1.00 | 1.00 |
| Accuracy focus | 0.844 | +0.033 [−0.022, +0.089] | $0.099 | 0.78 (p = 0.04) | 0.72 |
| **Cost focus** (6 samples) | **0.767** | **−0.057 [−0.151, +0.027]** | **$0.031** | **0.30 [0.24, 0.36]** | **0.55** |

Cost per solved task went from $0.16 (baseline) to $0.12 (accuracy focus) to $0.04 (cost focus).

### GPT-5.6 Sol

The Sol runs hit our OpenAI project's spending limit on the evening of 2026-10-28, after GEPA had finished but before the held-out test could run. We finished them on 2026-10-29 after the budget was raised. The runs that failed at the limit used no tokens, so we discarded and re-ran them.

| Note | Resolve rate | Change vs baseline [95% CI] | Cost per run | Cost ratio | Turns ratio |
|---|---|---|---|---|---|
| Baseline | 0.789 | | $1.96 | 1.00 | 1.00 |
| Accuracy focus | 0.733 | −0.056 [−0.133, +0.022] | $1.72 | 0.86 [0.79, 0.92] | 0.74 |
| **Cost focus** | **0.744** | **−0.044 [−0.156, +0.067]** | **$1.14** | **0.58 [0.55, 0.62]** | **0.60** |

Sol repeats the Luna pattern for cost. The accuracy-focus note saved 14%, and the cost-focus note saved 42% with every one of the 30 tasks cheaper. Cost per solved task went from $2.49 to $1.53. Sol is by far the most expensive model we tested at about $2 per run on the held-out tasks, so this is the largest saving in dollars of any model, about $0.82 per run.

The accuracy side looks more like Haiku 5.5 than Luna. Both notes solved slightly fewer tasks than the baseline (0.733 and 0.744 against 0.789). Neither drop is significant (p = 0.31 and 0.59), but both intervals reach below a 10-point loss, so we cannot claim either note is as accurate as the baseline. Sol's baseline is also the strongest of any model, at 79% on these hard tasks, which leaves the least room for a note to help.

### The other models (accuracy focus only)

| Model | Baseline resolve | Accuracy focus resolve (p) | Cost ratio (p) | Turns ratio |
|---|---|---|---|---|
| Claude Haiku 4.5 | 0.456 | 0.433 (0.88) | 1.03 (0.29) | 0.99 |
| Muse Glimmer 30B | 0.533 | 0.567 (0.73) | 0.95 (0.21) | 0.92 |
| Gemma 4 31B | 0.456 | 0.422 (0.64) | 1.08 (0.25) | 1.27 |
| gpt-oss-120b | 0.400 | 0.456 (0.45) | 0.80 (0.04) | 1.01 |
| Qwen3.6 27B | 0.478 | 0.489 (1.0) | 0.77 (<0.01) | 0.82 |

Qwen3.6 is the clearest example of the winner's problem from earlier. Its validation score went from 0.525 to 0.771, the largest validation gain of any model. On the held-out tasks the resolve rate moved from 0.478 to 0.489, i.e. one extra solved run out of 90, and the confidence interval spans an 11-point loss to a 13-point gain. The cost saving did carry over, though. The accuracy-focus note cut Qwen's cost to 0.77x (95% CI 0.66 to 0.89) with 18% fewer turns, which makes Qwen a strong candidate for a cost focus run at about $1 per run.

Two patterns stand out. The accuracy-focus notes did not change cost for Haiku 4.5, Muse or Gemma, and Gemma's note made it take 27% *more* turns. For gpt-oss-120b, the accuracy-focus note cut tokens per run by 21% without changing the number of turns, i.e. the agent read less per step rather than taking fewer steps. Qwen's note did both, with fewer turns and fewer tokens per run.

## What this means if you run coding agents

GEPA is a practical way to write a repository-specific system prompt, and the prompts it writes are readable. You can open them, see exactly what changed, and delete a rule you disagree with. That alone makes it more useful than tuning methods that produce opaque weights.

On our benchmark, the place GEPA paid off was cost, not accuracy, and it paid off most when we told it to care about cost. The cost-focus notes did not find a clever trick. They found the boring habits a good senior engineer would put in an onboarding note: don't fight the environment, read the function rather than the file, batch your searches, don't write scaffolding nobody will grade, and stop when you are done. Those habits cut Luna's cost by 42% with no detectable accuracy loss, Sol's by 42% and Haiku 5.5's by 70%.

The scope caution is the Haiku 5.5 result, and to a smaller degree Sol. A cost objective removes any advice whose value does not show up on the validation tasks, and with 20 validation tasks, protective advice like "update every caller" can look like dead weight. We would keep the cost weight small (we are considering 0.05 instead of 0.1), check the held-out accuracy with enough samples to bound the loss, and read the final note for missing safety rules before using it.

If you are paying per token for an agent that works in one codebase every day, the time to run this is before your next monthly bill, not after it. The Luna cost focus run (300 agent runs plus the reflector, about $30) pays for itself after roughly 1,000 tasks at $0.032 saved per task. For Sol, at $0.82 saved per task and roughly $400 for the run, the same arithmetic gives about 500 tasks.
