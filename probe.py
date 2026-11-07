"""
Routing probe: measure OpenRouter's default router directly by acting as a buyer who sets nothing.

Every hour, for every open-weight model with two or more paid sellers in the latest full snapshot, send a few
tiny requests and record which seller served each one. Two arms:
  short  a random nonce plus "Reply with the single word OK." (about 40 prompt tokens), every model
  long   the same plus about 500 tokens of random words, the 30 models with the most traffic
Requests carry no provider preferences, no app attribution headers and no optional parameters (extra
parameters can exclude sellers that do not support them): only model, messages, max_tokens 5 and usage
accounting. The random nonce makes every request a new conversation, so no prompt cache steers it.
The Mac and GitHub Actions each run the full sample (default 10 short per model + 2 long per long-arm model per hour).

Output: $PANEL_ROOT/probe/<UTC date>.csv.gz, one gzip member appended per run, one row per request:
  run, ts, source, model, arm, http, provider (seller that served it), model_returned, prompt_tokens,
  completion_tokens, cost (USD, from OpenRouter usage accounting), latency_s, error
Safety: stops at the first 401/402/403 and when a run has spent --budget dollars. The API key is read from
OPENROUTER_PROBE_KEY and never printed or written; without it the script exits quietly.
Run: python3 probe.py --source mac|cloud [--short 10] [--long 2] [--long-models 30] [--max-models N] [--out DIR]
"""
import argparse, csv, glob, gzip, io, json, os, random, sys, threading, time, uuid, datetime
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.expanduser(os.environ.get("PANEL_ROOT", "~/openrouter_panel"))
URL = "https://openrouter.ai/api/v1/chat/completions"
FIELDS = ["run", "ts", "source", "model", "arm", "http", "provider", "model_returned", "prompt_tokens",
          "completion_tokens", "cost", "latency_s", "error"]
WORDS = ("time year people way day man thing woman life child world school state family student group country "
         "problem hand part place case week company system program question work government number night point "
         "home water room mother area money story fact month lot right study book eye job word business issue "
         "side kind head house service friend father power hour game line end member law car city community name "
         "president team minute idea kid body information back parent face others level office door health person "
         "art war history party result change morning reason research girl guy moment air teacher force education").split()


def latest_snapshot(min_rows=1000):
    for path in sorted(glob.glob(os.path.join(ROOT, "snapshots", "*", "endpoints.csv.gz")), reverse=True):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if len(rows) >= min_rows:
            return os.path.dirname(path), rows
    sys.exit("no full snapshot found")


def probe_models(long_n):
    folder, rows = latest_snapshot()
    sellers, ow = {}, {}
    for r in rows:
        try:
            if float(r["p_in"] or 0) <= 0:
                continue
        except ValueError:
            continue
        sellers.setdefault(r["model"], set()).add(r["provider"])
        ow[r["model"]] = ow.get(r["model"], False) or r.get("open_weights") in ("True", "true", "1")
    models = sorted(m for m, s in sellers.items() if len(s) >= 2 and ow.get(m))
    traffic = {}
    stats = os.path.join(folder, "endpoint_stats.csv.gz")
    if os.path.exists(stats):
        with gzip.open(stats, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    traffic[r["model"]] = traffic.get(r["model"], 0) + float(r["requests"] or 0)
                except (ValueError, KeyError):
                    pass
    top = sorted(models, key=lambda m: -traffic.get(m, 0))[:long_n]
    return models, top


def prompt(arm):
    text = f"[{uuid.uuid4().hex}] "
    if arm == "long":
        text += " ".join(random.choice(WORDS) for _ in range(380)) + "\n\n"
    return text + "Reply with the single word OK."


def call(key, model, arm):
    body = {"model": model, "messages": [{"role": "user", "content": prompt(arm)}], "max_tokens": 5, "usage": {"include": True}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.load(r), time.time() - t, ""
    except urllib.error.HTTPError as e:
        return e.code, None, time.time() - t, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:
        return 0, None, time.time() - t, repr(e)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--short", type=int, default=10)
    ap.add_argument("--long", type=int, default=2)
    ap.add_argument("--long-models", type=int, default=30)
    ap.add_argument("--max-models", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--budget", type=float, default=0.10)
    ap.add_argument("--out", default=os.path.join(ROOT, "probe"))
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_PROBE_KEY")
    if not key:
        print("OPENROUTER_PROBE_KEY not set, skipping probe"); return
    models, top = probe_models(a.long_models)
    if a.max_models:
        models, top = models[:a.max_models], [m for m in top if m in models[:a.max_models]]
    jobs = [(m, "short") for m in models for _ in range(a.short)] + [(m, "long") for m in top for _ in range(a.long)]
    random.shuffle(jobs)
    now = datetime.datetime.now(datetime.timezone.utc)
    run = now.strftime("%Y-%m-%dT%H%MZ")
    rows, spent, stop, lock = [], 0.0, threading.Event(), threading.Lock()

    def work(job):
        if stop.is_set():
            return None
        m, arm = job
        code, d, lat, err = call(key, m, arm)
        u = (d or {}).get("usage") or {}
        return {"run": run, "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": a.source,
                "model": m, "arm": arm, "http": code, "provider": (d or {}).get("provider"), "model_returned": (d or {}).get("model"),
                "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                "cost": float(u.get("cost") or 0), "latency_s": round(lat, 3), "error": err}

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, j) for j in jobs]
        for f in as_completed(futs):
            r = f.result()
            if r is None:
                continue
            with lock:
                rows.append(r); spent += r["cost"]
                if r["http"] in (401, 402, 403) or spent > a.budget:
                    stop.set()
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"{now:%Y-%m-%d}.csv.gz")
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=FIELDS)
    if not os.path.exists(path):
        w.writeheader()
    w.writerows(rows)
    with gzip.open(path, "at", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
    ok = sum(r["http"] == 200 for r in rows)
    errs = sorted({r["error"][:80] for r in rows if r["error"]})[:3]
    print(f"{run} {a.source}: {len(rows)}/{len(jobs)} requests, {ok} ok, ${spent:.4f} spent, {len(models)} models"
          + (" | STOPPED early" if stop.is_set() else "") + (f" | errors: {errs}" if errs else ""))


if __name__ == "__main__":
    main()
