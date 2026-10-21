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
