# Keywords & Niches

## 10 active DR niches

| Niche | Keywords | Top mechanism |
|-------|----------|---------------|
| `weight_loss` | 14 | "gelatin trick", "belly fat trick" |
| `diabetes` | 13 | "blood sugar trick", "reverse diabetes" |
| `ed` | 13 | "salt trick", "blood flow trick" |
| `memory` | 13 | "memory trick", "brain ritual" |
| `back_pain` | 12 | "sciatic nerve trick", "back pain ritual" |
| `vision` | 13 | "vision trick", "blurry vision trick" |
| `prostate` | 12 | "prostate trick", "stop waking up at night" |
| `sleep` | 13 | "sleep trick", "sleep ritual" |
| `blood_pressure` | 13 | "blood pressure morning ritual" |
| `neuropathy` | 13 | "neuropathy trick", "nerve pain trick" |

**Total: 129 keywords**

## Keyword position strategy (Gustavo Rafaell method)

FB's `keyword_unordered` finds any ad where ALL your words appear anywhere in the transcript or copy — order doesn't matter. This means:

```
Position 1-2:  Symptom / mechanism anchor
               "blood sugar", "belly fat", "salt", "gelatin"

Position 3:    DR signal word  ← most important filter
               trick / ritual / hack / secret / recipe / method
               Adding "trick" to any symptom → ONLY DR creatives appear

Position 4:    Qualifier (surfaces different advertisers)
               morning / ancient / recipe / japanese / bedroom
```

### Example expansion (Gustavo's technique)
```
"blood sugar"           → broad, finds all content about blood sugar
"blood sugar trick"     → DR filtered, finds only direct response ads
"blood sugar trick recipe" → finds different advertisers with ingredient angle
"blood sugar morning trick" → finds time-based hook advertisers
```

Each addition of a word surfaces a DIFFERENT set of advertisers.

## Volume benchmarks (confirmed, US English)

| Keyword | Total | Video | Image |
|---------|-------|-------|-------|
| gelatin trick | 50,000 | 50,000 | 180 |
| belly fat | 50,000 | 50,000 | 2,200 |
| belly fat trick | 32,000 | 31,000 | 58 |
| weight loss trick | 33,000 | 27,000 | 140 |
| blood sugar trick | 15,000 | 10,000 | 1,800 |
| boost metabolism | 15,000 | 4,600 | 530 |

## Expanding keywords

```bash
# Run 3-word variants of all base keywords
python -m agents.count_agent --niche weight_loss --expand

# This generates: "blood sugar trick", "blood sugar trick morning",
#                 "blood sugar trick recipe", etc.
```

## Adding new keywords

Edit `core/keywords.py` → find the relevant niche dict → add the keyword string.
New keywords picked up on next pipeline run automatically.
