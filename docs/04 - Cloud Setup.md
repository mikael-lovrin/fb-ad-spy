# Cloud Setup

## Architecture

```
GitHub Actions (CI)
  ├── Stage 1 jobs: 10 niches × separate runner = 10 different IPs
  ├── Stage 2 jobs: metadata extraction, after Stage 1
  └── Stage 3+4 jobs: download + Claude analysis

        ↓ all write to ↓

Supabase (PostgreSQL)
  ├── keyword_snapshots  (Stage 1 output)
  └── ads                (Stage 2+ output)
```

## Supabase

**Project:** fb-ad-spy
**Region:** (your region)
**Database:** PostgreSQL 17.6

Connection string (stored in GitHub Secrets, NOT in code):
`postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres`

> ⚠️ The `@` in the password must be encoded as `%40` in the URL.
> Example: password `Abc@123` → `Abc%40123` in the URL.

### Free tier limits
- 500 MB storage
- Unlimited reads/writes
- 2 projects max

---

## GitHub Actions

**Repo:** github.com/mikael-lovrin/fb-ad-spy

### Schedules
| Workflow | Cron (UTC) | BRT time | What runs |
|----------|-----------|----------|-----------|
| `daily_stage1.yml` | `0 8 * * *` | 5AM | Count all 10 niches |
| `daily_stage1.yml` | `0 20 * * *` | 5PM | Count all 10 niches again |
| `daily_stage2.yml` | `0 13 * * *` | 10AM | Metadata for keywords >5k ads |
| `daily_stage3_4.yml` | `0 17 * * *` | 2PM | Download + Claude analysis |

### IP rotation mechanism
Each matrix niche = separate GitHub runner = different IP from Azure's pool.
With 5-min cooldown between niches, FB never sees a burst from one IP.

### Secrets needed
Go to: Repo → Settings → Secrets and variables → Actions

| Secret | Value |
|--------|-------|
| `DATABASE_URL` | Supabase PostgreSQL URI (with %40 encoding) |
| `ANTHROPIC_API_KEY` | From console.anthropic.com |

### Manual trigger
Actions tab → pick workflow → "Run workflow" button → run for a single niche or all.

---

## Docker (local testing)

```bash
# Build image
docker build -t fb-ad-spy .

# Run Stage 1 for diabetes niche
docker run --env-file .env fb-ad-spy agents.count_agent --niche diabetes

# Full pipeline
docker run --env-file .env fb-ad-spy pipeline --niche weight_loss

# Interactive shell
docker run -it --env-file .env --entrypoint bash fb-ad-spy
```

```bash
# Or with docker-compose
docker-compose run --rm spy agents.count_agent --niche diabetes
```

---

## GitHub Actions free tier note

Private repos: **2,000 min/month free**.
Stage 1 for all niches takes ~80 min × 2 runs/day = 160 min/day = 4,800 min/month.

**To stay free:** make the repo public (code has no secrets — all keys are in Secrets).
Public repos: **unlimited free minutes**.

To make public: Repo → Settings → Danger Zone → Change visibility → Public.
