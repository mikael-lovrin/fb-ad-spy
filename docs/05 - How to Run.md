# How to Run

## Local setup

```bash
# 1. Activate virtual environment (Windows)
.venv\Scripts\activate

# 2. Copy .env.example to .env and fill in your keys
cp .env.example .env

# 3. Install dependencies (first time only)
pip install -r requirements.txt
playwright install chromium --with-deps
```

---

## Running individual stages

### Stage 1 — Count keywords
```bash
# One niche
python -m agents.count_agent --niche diabetes

# All niches
python -m agents.count_agent --all

# With slower delay (if getting 100-count throttle)
python -m agents.count_agent --niche weight_loss --delay 30

# With keyword expansion (3-word variants)
python -m agents.count_agent --niche weight_loss --expand

# Single keyword test
python -m agents.count_agent --keyword "blood sugar trick" --niche diabetes
```

### Stage 2 — Collect individual ad metadata
```bash
# One niche, only keywords with >5000 ads
python -m agents.metadata_agent --niche diabetes --min-ads 5000

# Specific keyword
python -m agents.metadata_agent --keyword "belly fat trick" --count 50

# All keywords in niche (no minimum)
python -m agents.metadata_agent --niche weight_loss --count 100
```

### Stage 3 — Download media
```bash
# Download for all pending ads
python -m agents.download_agent

# Limit to 100 ads
python -m agents.download_agent --limit 100
```

### Stage 4 — Claude analysis
```bash
# Analyze 50 unanalyzed ads
python -m agents.analyze_agent

# Only video ads
python -m agents.analyze_agent --video-only --limit 20

# Only image ads
python -m agents.analyze_agent --image-only --limit 20
```

---

## Full pipeline
```bash
# Collect + analyze for one niche
python pipeline.py --niche diabetes

# Count only (no Claude costs)
python pipeline.py --niche weight_loss --count-only

# Skip Stage 1 (if already have fresh counts)
python pipeline.py --niche diabetes --skip-count

# Only high-volume keywords (>5000 ads)
python pipeline.py --niche weight_loss --min-ads 5000
```

---

## Checking results

```bash
# Show DB stats
python main.py --stats

# Show latest Supabase snapshots
python check_supabase.py

# Start dashboard
streamlit run dashboard/app.py
```

---

## Throttle detection

If Stage 1 returns 100 for everything:
1. Stop all runs
2. Wait 30-60 minutes
3. Re-run with `--delay 30`

Signs of throttle:
- `total == video == image == 100` for 3+ consecutive keywords
- The count_agent logs "throttled streak" warnings
