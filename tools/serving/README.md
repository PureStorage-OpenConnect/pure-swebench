# Local open-weight serving

> Currency: CURRENT. Owner: serving. Current-number policy: dynamic;
> `serve_local.sh status` is the live truth.

This directory holds everything needed to serve the local open-weight models that the
`pi-vllm-*` agent rows use. Before it existed, the serve commands lived only in shell
history, which made a working configuration impossible to reproduce.

**`models.conf` is a REFERENCE configuration, not a portable one.** Its GPU indices,
ports and tensor-parallel sizes are an example layout for a generic 8-GPU server
(see `docs/on-prem-gpu-sizing.md` to size it for yours). Edit that table for your own hardware before the first `start` -- everything else here
is machine-independent.

## Files

| File | Purpose |
|---|---|
| `models.conf` | The serving table. One line per model. Edit this, not the scripts. |
| `setup_venv.sh` | Build the vLLM virtualenv. `--verify` checks an existing one. |
| `serve_local.sh` | `start` / `stop` / `status` / `check` the servers. |
| `muse_debug.py` | Diagnostic for a model that serves but emits garbage. |

## Quick start

```bash
bash tools/serving/setup_venv.sh              # once per machine
bash tools/serving/setup_venv.sh --muse-fork  # only if you want Muse Glimmer
bash tools/serving/serve_local.sh start       # start everything in models.conf
bash tools/serving/serve_local.sh status      # poll until all READY (minutes)
bash tools/serving/serve_local.sh check       # PROVE tool calling works
```

`status` only says a server answered. **`check` is the one that matters**: it sends a
real tools request and asserts the model returns `finish_reason=tool_calls`. A server
can be READY and still be useless to the harness.

## Why the venv is not in this repo

The vLLM venv is about 7.7 GB and each model is roughly 60 GB, so neither belongs in git.
`setup_venv.sh` is the reproducible recipe; its output is deliberately untracked.

Everything derives from **one** knob:

```bash
export ZBENCH_SERVING_ROOT=/path/to/zbench-serving   # venvs + weights + logs
```

It defaults to `<repo>/.serving` (gitignored), so a fresh clone works with no
configuration. Point it at bulk storage if your root disk is small -- five models plus the
venv is roughly 300 GB. `ZBENCH_VLLM_VENV`, `ZBENCH_HF_HOME` and `ZBENCH_SERVING_LOGS`
override the individual paths if you need them split across filesystems.

## Why three stacks

The cohort runs on three different vLLM builds. That is not tidiness lost for no reason
-- each model fails outright on the others, and each case is recorded below so nobody
re-litigates it.

| stack | vLLM | models | why |
|---|---|---|---|
| `venv` | 0.27.1 (PyPI) | gpt-oss, Qwen3.6, Nemotron | the default |
| `docker` | 0.21.0 (image) | Gemma 4 | needs an OLDER vLLM |
| `venv:vllm-muse` | `0.1.dev1+gc4dc585` (fork) | Muse Glimmer | needs an UNMERGED branch |

**Record the engine per row in `agents-meta.jsonl`.** A score from a model on a
different engine version reflects the engine as well as the model, so the rows are not
strictly comparable without that annotation.

### Muse Glimmer: an unmerged branch

Muse needs vLLM from upstream PR #51655 (`xianbaoqian/vllm`, branch
`tiezhen/new-model-support`, pinned at `c4dc585`), which adds **the native model
implementation** plus the `muse_glimmer` tool and reasoning parsers.

The native implementation is the load-bearing half. On a stock vLLM there is no Muse
implementation, so it silently falls back to the generic Transformers backend and every
generation is garbage -- multilingual noise between correct channel markers. The parsers
alone cannot fix that; they would organise noise. The log line tells you which you have:

```
stock: Resolved architecture: TransformersMultiModalForCausalLM ... falling back to Transformers backend
fork : Resolved architecture: MuseGlimmerForConditionalGeneration
```

Verified working on the fork: coherent generation, correct multi-step arithmetic, and
`finish_reason=tool_calls` with well-formed arguments. Two caveats:
`reasoning_content` stays `None` (the reasoning lands in `content`, so reasoning tokens
cannot be measured separately), and `tool_choice="required"` / named tool choice are
unsupported -- irrelevant to this harness, which only uses `"auto"`.

When the PR reaches a release: rebuild the default venv, change Muse's stack to `venv`
in `models.conf`, and delete the `--muse-fork` mode from `setup_venv.sh`.

### Gemma 4: an older vLLM

**Gemma 4 runs in docker on vLLM 0.21.x** because it cannot load on 0.27.1 at all:

| stack | Gemma 4 result |
|---|---|
| vLLM 0.27.1 + transformers 5.15.0 | `AmbiguousGlobalPerLayerAttributeError: 'head_dim' is a per-layer attribute` |
| same, forcing `allow_global_per_layer_attribute_access` | passes config, then `Attempted to load weight (512) into parameter (256)` |
| **vLLM 0.21.0 + transformers 5.8.1 (docker)** | **loads and generates correctly** |

Gemma 4 uses a different head dimension on different layers. transformers 5.15 refuses
to report one global value, and forcing it builds the model with wrong shapes. The older
pairing handles it. 0.27.1 is the newest vLLM on PyPI, so there is no forward fix yet --
when one lands, move Gemma to `venv` in `models.conf` and delete this note.

**Record this in `agents-meta.jsonl`**: a Gemma score reflects its engine version as well
as the model, so it is not strictly comparable to rows served by 0.27.1.

## Traps that cost real time

- **`PATH` must include the venv `bin`.** vLLM shells out to `ninja` during startup
  profiling. Launching `vllm` by absolute path without it dies with
  `[Errno 2] No such file or directory: 'ninja'` -- which looks like a GPU/memory
  failure and is not.
- **Start servers detached.** `nohup ... & disown`, so `PPID` becomes 1. A server tied
  to an interactive shell or an agent's background task dies with that session.
- **Never `pkill -f <model-name>`.** `-f` matches the caller's own command line, so it
  kills the shell that ran it. Stop by port instead (`serve_local.sh stop`, which uses
  `lsof -ti :PORT`).
- **Tensor parallelism is not free.** Multimodal projectors can be sharded incorrectly:
  Muse Glimmer fails at TP=2 with `16384x768 vs 1536x1536` and needs TP=1.
- **Do not set `HF_HUB_ENABLE_HF_TRANSFER=1`.** The `hf_transfer` extra was removed in
  `huggingface_hub` 1.x; `hf_xet` replaces it and the env var raises on a missing module.
- **`hf download --exclude "a" "b"` mis-parses** the second pattern as a filename. Use
  `snapshot_download(ignore_patterns=[...])`.

## Context length

Every row is pinned to `--max-model-len 131072`, because METHODOLOGY sec.6 wants one
context budget across agents so a score reflects the model rather than its allowance.
64k was measurably too small for harder tasks.

**pi DOES compact.** An earlier version of this file claimed it did not. Session logs
disprove that: pi writes a `{"type":"compaction"}` record with a summary when the context
approaches the limit, observed on gpt-oss (118k input), Muse (99k), Nemotron (99k) and
Gemma (95k) in `local-py10`. So an overflowing task degrades rather than failing outright.

That changes how a long-task score reads: a compacted attempt lost history, so a miss on a
context-heavy task may reflect summarisation loss rather than the model's reasoning. Count
compactions per session before drawing a conclusion:

```bash
grep -c '"type":"compaction"' bench-db/.runtime/cells/<cell>/session.jsonl
```

Splitting a model across two GPUs buys more than the extra context. Qwen3.6-27B went
from 2.2x to 10.9x concurrency at 128k on the second card, because moving the weights
off one card frees far more KV room than the shard costs.

## Known-bad models

**Nemotron 3 Ultra 550B** is not served here: the official 4-bit release is NVFP4, which
needs Blackwell. On an older-generation reference server it would also need 6-8 GPUs and a
self-made AWQ/GPTQ checkpoint. On Blackwell hardware it may serve directly -- re-test
rather than inheriting this verdict.

## Debugging a model that serves but emits garbage

`muse_debug.py` runs a model through plain transformers with **no vLLM involved**, which
splits the two possible causes:

```bash
"$ZBENCH_SERVING_ROOT/venvs/vllm/bin/python" tools/serving/muse_debug.py
```

Clean text there means the weights are fine and the serving layer is the bug. Garbage
there too means the weights or config are wrong and no serving stack will help. Needs a
free GPU.

That distinction is what Muse turned on: the weights were always fine, and vLLM's
generic fallback was producing the noise. Two search habits are worth copying, because
both models were wrongly written off first:

- a stock release being newest does NOT mean a fix does not exist -- Muse's was on an
  unmerged branch;
- newer is not always the fix -- Gemma's was an OLDER release.

Check both directions before calling a model unsupported, and **launch it** rather than
concluding from a registry lookup.

## Wiring a served model into the harness

A running server is not yet a benchmark row. Each model also needs:

1. a provider block in `~/.pi/agent/models.json` -- **one per port**, since a provider
   carries a single `baseUrl`;
2. an agent row in `zbench-tasks/agents-custom.jsonl` (and `agents-matrix.jsonl` to be
   ranked) whose `PI_MODEL` is the `alias` from `models.conf`;
3. a sourced `training_cutoff` in `agents-meta.jsonl` -- METHODOLOGY sec.5 requires it
   before a row may appear on a ranked board;
4. `effort_evidence: not_delivered` -- `PI_THINKING` does NOT reach a vLLM backend, so
   these rows are effort-uncontrolled in the same way codex rows are.
