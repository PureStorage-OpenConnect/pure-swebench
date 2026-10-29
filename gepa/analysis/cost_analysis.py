"""GEPA cost analysis: does an optimized prompt change cost / tokens / turns / time per task?

Part 1 (held-out test tasks): seed vs each optimized prompt, paired by task.
Part 2 (validation tasks): every GEPA candidate vs seed, paired by task (GEPA never selected on cost,
so these pairs carry no selection bias for cost).
Cost = tools/model_prices.cost_usd (board price table; open-weight models at public-host price).
"""
import json, math, random, sqlite3, sys
from pathlib import Path

R = Path("/mnt/data/robert-scripts/pure-swebench")
G = R / "gepa"
sys.path[:0] = [str(R / "tools"), str(G)]
import model_prices as mp  # noqa
from gepa_run_cost import session_cost  # noqa  (tiered per-request cost; Haiku 5.5 >100K prompts = 5x)
from rollout_runner import candidate_id, _session_output_tokens  # noqa

MODELS = ["pi-openai-gpt-5.6-luna", "pi-anthropic-haiku-4-5", "pi-vllm-muse-glimmer-30b",
          "pi-vllm-gemma-4-31b", "pi-vllm-qwen3.6-27b", "pi-anthropic-haiku-5-5",
          "pi-vllm-gpt-oss-120b", "pi-openai-gpt-5.6-sol"]
db = sqlite3.connect(f"file:{G}/store/bench.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
EXCL = {r[0] for r in db.execute("select evaluation_id from run_exclusion")}
TASKS = json.load(open(G / "tasks.json"))
VAL, TEST = TASKS["train"], TASKS["test"]
METRICS = ["cost", "tokens", "out_tok", "turns", "minutes"]


def cells(cfg, tasks):
    """latest valid attempt per task for one config -> {task: metrics}"""
    out = {}
    q = "select * from attempt where config_id=? and task_id in (%s) order by finished_at" % ",".join("?" * len(tasks))
    for r in db.execute(q, [cfg, *tasks]):
        if r["evaluation_id"] in EXCL or r["status"] == "provider_error":
            continue
        # API refusals (e.g. the OpenAI spend limit) have 0 tokens in the row AND in the session.
        # No-patch rows have empty token columns but real session usage (Haiku 5.5 thinking-only
        # failures), so they are kept.
        if not (r["input_tokens"] or r["output_tokens"]) and not _session_output_tokens(r["evaluation_id"]):
            continue
        base = cfg.split("--")[0]
        c = session_cost(base, r["evaluation_id"],
                         mp.cost_usd(base, r["input_tokens"], r["output_tokens"], r["cache_read_tokens"], r["cache_write_tokens"]))
        out[r["task_id"]] = dict(cost=c, tokens=(r["input_tokens"] or 0) + (r["output_tokens"] or 0) +
                                 (r["cache_read_tokens"] or 0) + (r["cache_write_tokens"] or 0),
                                 out_tok=r["output_tokens"] or 0, turns=r["turns"] or 0,
                                 minutes=(r["runtime_ms"] or 0) / 60000, resolved=r["tests_passed"])
    return out


def arm(base, prompt, tasks, samples):
    """per-task mean of each metric over the available samples"""
    per = [cells(candidate_id(base, prompt, k), tasks) for k in samples]
    res = {}
    for t in tasks:
        xs = [p[t] for p in per if t in p]
        if xs:
            res[t] = {m: sum(x[m] for x in xs) / len(xs) for m in METRICS + ["resolved"]}
            res[t]["n"] = len(xs)
    return res


def sign_flip_p(d, n=50_000, seed=0):
    obs = abs(sum(d)); rng = random.Random(seed)
    hits = sum(abs(sum(x if rng.random() < .5 else -x for x in d)) >= obs - 1e-12 for _ in range(n))
    return (hits + 1) / (n + 1)


def compare(a, b):
    """b vs a, paired by task. Ratio = exp(mean log ratio) (geometric mean), p on log ratios."""
    ts = [t for t in a if t in b]
    out = {"n_tasks": len(ts)}
    for m in METRICS:
        pairs = [(a[t][m], b[t][m]) for t in ts if a[t][m] and b[t][m]]
        lr = [math.log(y / x) for x, y in pairs]
        out[m] = dict(seed_mean=sum(x for x, _ in pairs) / len(pairs), new_mean=sum(y for _, y in pairs) / len(pairs),
                      geo_ratio=math.exp(sum(lr) / len(lr)), down=sum(v < 0 for v in lr), up=sum(v > 0 for v in lr),
                      p=sign_flip_p(lr)) if pairs else None
    ra, rb = sum(a[t]["resolved"] for t in ts), sum(b[t]["resolved"] for t in ts)
    ca, cb = sum(a[t]["cost"] or 0 for t in ts), sum(b[t]["cost"] or 0 for t in ts)
    out.update(resolved_seed=ra, resolved_new=rb, cost_seed=ca, cost_new=cb,
               cost_per_resolve_seed=ca / ra if ra else None, cost_per_resolve_new=cb / rb if rb else None)
    return out


def summary(d):
    return json.load(open(d / "summary.json"))


report = {"test": {}, "val": {}}
for m in MODELS:
    arms = {"v1_best": (summary(G / "runs" / m)["best_prompt"], [1])} if (G / "runs" / m / "summary.json").is_file() else {}
    v2name = "v2_limit600" if "haiku-4-5" in m else "v2_nolimit"   # local runs-v2 restarted without the limit
    for name, d in ((v2name, G / "runs-v2" / m), ("v2_nolimit", G / "runs-v2-nolimit" / m), ("cost_aware", G / "runs-cost" / m)):
        if (d / "test_eval.json").is_file():
            arms[name] = (summary(d)["best_prompt"], [1, 2, 3])
    for name, (prompt, smp) in arms.items():
        report["test"][f"{m} | {name}"] = compare(arm(m, "", TEST, smp), arm(m, prompt, TEST, smp))
    # validation: every candidate of every run vs seed (seed averaged over the same samples)
    for run, d in (("v1", G / "runs" / m), (v2name, G / "runs-v2" / m), ("v2_nolimit", G / "runs-v2-nolimit" / m),
                   ("cost_aware", G / "runs-cost" / m)):
        f = d / "candidates.json"
        if not f.is_file():
            continue
        smp = [1] if run == "v1" else [1, 2, 3]
        seed = arm(m, "", VAL, smp)
        cands = json.load(open(f))
        cands = [c.get("append_system_prompt", c) if isinstance(c, dict) else c for c in cands]
        for i, p in enumerate(cands):
            if not (p or "").strip():
                continue
            new = arm(m, p, VAL, smp)
            if len(new) >= 6:
                report["val"][f"{m} | {run} | cand{i} ({len(p.split())}w)"] = compare(seed, new)

json.dump(report, open(sys.argv[1], "w"), indent=1)


def fmt(k, r):
    g = lambda mm: (f"{r[mm]['geo_ratio']:.2f} ({r[mm]['down']}v/{r[mm]['up']}^ p={r[mm]['p']:.2f})" if r[mm] else "-")
    cps = lambda x: f"{x:.2f}" if x is not None else "-"
    print(f"{k:58s} n={r['n_tasks']:2d} cost {g('cost'):24s} tok {g('tokens'):24s} turns {g('turns'):24s} "
          f"min {g('minutes'):24s} res {r['resolved_seed']:.1f}->{r['resolved_new']:.1f} "
          f"$/res {cps(r['cost_per_resolve_seed'])}->{cps(r['cost_per_resolve_new'])}")


print("== HELD-OUT TEST (ratio new/seed, geometric mean over tasks; v=tasks cheaper, ^=tasks dearer)")
for k, r in report["test"].items():
    fmt(k, r)
print("\n== VALIDATION, every candidate vs seed")
for k, r in report["val"].items():
    fmt(k, r)
