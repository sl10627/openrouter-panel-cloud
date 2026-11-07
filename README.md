# OpenRouter price-dispersion panel (cloud collector)

Four times a day, GitHub Actions runs `snapshot.py` and commits one folder to `snapshots/<UTC time>/`:

| file | contents |
|---|---|
| `models.csv.gz` | every model: id, slug, Hugging Face id, list prices, context |
| `endpoints.csv.gz` | every provider endpoint of every paid model (official API): provider, tier/region tag, prices, quantization, uptime |
| `endpoint_stats.csv.gz` | per-provider latency, throughput, 30-min request count, data policy, HQ (website's internal stats endpoint, unofficial) |

This is the backup to a Mac launchd job running the same script at the same times. Both sets are merged by
`~/openrouter_panel/build_panel.py`, which adds a `source` column (`mac` / `cloud`).

Only public endpoints are called; there is no API key or secret in this repo.

- Manual run: Actions tab → openrouter-snapshot → Run workflow.
- Pause: Actions tab → openrouter-snapshot → ··· → Disable workflow.

Once a day (the first hourly run of each UTC day), `azure_prices.py` also saves Microsoft Azure's public list prices
for AI models (Retail Prices API, `Foundry Models`, all regions) to `azure/<UTC date>.csv.gz`. List prices only, no usage.

Every hourly run, `other_platforms.py` also records the same models on two other marketplaces, to compare the same
seller's prices across platforms:

| folder | source | contents |
|---|---|---|
| `hf/<UTC date>.csv.gz` | Hugging Face Inference Providers (`router.huggingface.co/v1/models`) | every model x provider: price, status, HF-measured time to first token and throughput |
| `vercel/<UTC date>.csv.gz` | Vercel AI Gateway (`ai-gateway.vercel.sh/v1/models/{id}/endpoints`) | every language model x provider: prices (cache, discount, peak-hour multiplier), status, uptime, latency, throughput |
| `vercel_leaderboard/<UTC date>/` | Vercel AI Gateway leaderboard export (CC BY 4.0), once a day | anonymized daily usage shares by model and lab, all-time provider ranking |

Batch-only Vercel models have no endpoint list (404) and are skipped. Public endpoints only, no key.

Every hourly run, `probe.py` also sends a few tiny requests of its own to every open-weight model with two or more
paid sellers and records which seller OpenRouter's default router picked (`probe/<UTC date>.csv.gz`): 10 short
requests per model and 2 longer ones (about 500 tokens) for the 30 busiest models, with no provider preferences.
The same script runs on the Mac. It needs the repository secret `OPENROUTER_PROBE_KEY` (the API key is never stored
in the repo) and skips itself when the secret is missing.

