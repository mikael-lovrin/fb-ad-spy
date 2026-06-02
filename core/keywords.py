# -*- coding: utf-8 -*-
"""
FB Ad Library keyword system — English, DR-focused, US market.

Based on Gustavo Rafaell benchmark method + English DR market analysis.

POSITION STRATEGY (for keyword_unordered):
  Position 1-2:  Symptom/mechanism (what the audience experiences)
                 e.g. "blood sugar", "belly fat", "salt"
  Position 3:    DR signal (filters to direct-response only)
                 trick / ritual / hack / secret / recipe / method / protocol
                 Adding "trick" to any symptom → instantly surfaces DR creatives
  Position 4:    Qualifier (surfaces different advertisers per the Gustavo method)
                 morning / ancient / recipe / simple / bedroom / japanese

  Example expansion: "blood sugar" → "blood sugar trick" → "blood sugar morning trick"
                     "belly fat" → "belly fat trick" → "belly fat trick recipe"

NICHES (10 confirmed active DR niches in English US market):
  weight_loss, diabetes, ed, memory, back_pain,
  vision, prostate, sleep, blood_pressure, neuropathy

Source references:
  spy-tutorial.txt  — Gustavo Rafaell method (weight loss, diabetes, memory, ED, neuropathy)
  English DR market — back_pain, vision, prostate, sleep, blood_pressure confirmed active
"""

from itertools import product

# DR signal words — using one as the 3rd word filters any symptom term to DR content
DR_SIGNALS = ["trick", "ritual", "hack", "secret", "recipe", "method", "protocol"]

# Qualifiers — add as 4th word to surface different advertisers
DR_QUALIFIERS_4TH = [
    "morning", "ancient", "simple", "bedroom", "japanese",
    "recipe", "works", "no diet", "without exercise",
]


def generate_variants(base: str, max_words: int = 4) -> list[str]:
    """
    Generate keyword variants by appending DR qualifiers to a base phrase.
    Only generates when base has room for more words.
    Returns [base] + [base + qualifier, ...].
    """
    results = [base]
    n = len(base.split())
    if n < max_words:
        for q in DR_QUALIFIERS_4TH:
            candidate = f"{base} {q}"
            if len(candidate.split()) <= max_words:
                results.append(candidate)
    return results


# ---------------------------------------------------------------------------
# KEYWORD DEFINITIONS
#
# Each niche has ~12 keywords organized as:
#   - Broad symptoms (2 words)        — high volume, discovers all advertisers
#   - Mechanism + DR signal (2-3 w)   — filtered to DR content
#   - Brand/drug comparisons (1-2 w)  — competitor + alternative angle
#   - Ingredient mechanisms (2-3 w)   — "gelatin trick" style
#
# These feed Stage 1 (count) and Stage 2 (metadata collection).
# ---------------------------------------------------------------------------

KEYWORDS = {

    # -----------------------------------------------------------------------
    # WEIGHT LOSS — largest DR niche, ~50k+ ads for top keywords
    # Confirmed hot mechanisms: gelatin trick, ice hack, salt trick
    # -----------------------------------------------------------------------
    "weight_loss": [
        # Broad symptoms (position 1-2)
        "belly fat",
        "lose weight",
        # Mechanism + DR signal (position 1-2 + trick/ritual)
        "belly fat trick",
        "weight loss trick",
        "fat burning ritual",
        "morning ritual weight loss",
        "ice hack weight loss",
        # Ingredient mechanisms (Gustavo: "gelatin", "soda", "recipe" as 3rd words)
        "gelatin trick",
        "coffee trick weight loss",
        "cinnamon trick weight loss",
        # Brand/drug comparison
        "ozempic alternative",
        "semaglutide",
        # Desire-based (no restriction angle)
        "no diet no exercise",
        "lose weight without dieting",
    ],

    # -----------------------------------------------------------------------
    # DIABETES — 2nd largest, "blood sugar" is the universal anchor
    # "trick" as 3rd word = DR filtered, "type 2" = condition anchor
    # -----------------------------------------------------------------------
    "diabetes": [
        # Broad base
        "blood sugar",
        "type 2 diabetes",
        # DR-filtered mechanisms
        "blood sugar trick",
        "blood sugar morning ritual",
        "reverse diabetes trick",
        "lower blood sugar naturally",
        # Ingredient mechanisms
        "cinnamon blood sugar",
        "apple cider vinegar blood sugar",
        "berberine blood sugar",
        # Brand/drug angle
        "metformin alternative",
        "ozempic",
        # Condition anchors
        "insulin resistance trick",
        "a1c levels",
    ],

    # -----------------------------------------------------------------------
    # ERECTILE DYSFUNCTION — "salt trick" went massively viral in DR
    # "every man over 40" is a classic audience-hook mechanism
    # -----------------------------------------------------------------------
    "ed": [
        # Top viral mechanisms
        "salt trick",
        "blood flow trick",
        "10 second trick",
        # Audience hooks
        "every man over 40",
        "every man over 50",
        # Symptom + DR signal
        "erectile dysfunction trick",
        "hard erection trick",
        "bedroom performance trick",
        # Brand/drug angle
        "blue pills alternative",
        "viagra alternative",
        "tadalafil alternative",
        # Ingredient mechanisms
        "nitric oxide trick",
        "testosterone trick",
    ],

    # -----------------------------------------------------------------------
    # MEMORY — Gustavo: "memória", uses "ritual" and "protocol" as signals
    # "brain fog" is a high-volume anchor, "over 50" audience hook works well
    # -----------------------------------------------------------------------
    "memory": [
        # Broad base
        "brain fog",
        "memory loss",
        # DR-filtered mechanisms
        "memory trick",
        "brain ritual",
        "memory ritual",
        "brain fog trick",
        "sharpen memory trick",
        # Audience hooks
        "memory loss over 50",
        "brain fog morning",
        # Ingredient mechanisms
        "lion mane brain",
        "omega 3 memory",
        # Protocol/method angle
        "brain protocol",
        "cognitive decline trick",
    ],

    # -----------------------------------------------------------------------
    # BACK PAIN — sciatica is the highest-volume anchor
    # "sciatic nerve" + "trick" is a proven DR combination
    # -----------------------------------------------------------------------
    "back_pain": [
        # Broad base
        "back pain",
        "sciatic nerve",
        # DR-filtered mechanisms
        "back pain trick",
        "sciatic nerve trick",
        "sciatica ritual",
        "relieve back pain",
        # Specific conditions
        "lower back pain trick",
        "herniated disc trick",
        "spine pain trick",
        # Outcome-based
        "end back pain",
        "back pain morning ritual",
        "neuropathy trick",
    ],

    # -----------------------------------------------------------------------
    # VISION — "blurry vision" is the anchor, often appears in diabetes ads too
    # "restore vision" + DR signal finds ophthalmology supplement advertisers
    # -----------------------------------------------------------------------
    "vision": [
        # Broad base
        "blurry vision",
        "vision loss",
        # DR-filtered mechanisms
        "vision trick",
        "blurry vision trick",
        "restore vision trick",
        "eye hack",
        # Condition anchors
        "macular degeneration trick",
        "eye floaters trick",
        "cataracts trick",
        # Ingredient mechanisms
        "lutein vision",
        "bilberry eye trick",
        # Outcome-based
        "crystal clear vision",
        "restore 20/20 vision",
    ],

    # -----------------------------------------------------------------------
    # PROSTATE — "enlarged prostate" is the anchor, men's health niche
    # "stop waking up at night" is a powerful audience-hook mechanism
    # -----------------------------------------------------------------------
    "prostate": [
        # Broad base
        "enlarged prostate",
        "frequent urination",
        # DR-filtered mechanisms
        "prostate trick",
        "prostate ritual",
        "enlarged prostate trick",
        "urinary trick",
        # Symptom hooks
        "stop waking up at night",
        "weak urine stream trick",
        # Ingredient mechanisms
        "saw palmetto prostate",
        "beta sitosterol prostate",
        # Brand/condition angle
        "benign prostatic hyperplasia",
        "prostate health morning",
    ],

    # -----------------------------------------------------------------------
    # SLEEP — "sleep trick" growing fast, "insomnia" is the anchor
    # Time-based hooks work well: "fall asleep in 5 minutes"
    # -----------------------------------------------------------------------
    "sleep": [
        # Broad base
        "insomnia",
        "sleep better",
        # DR-filtered mechanisms
        "sleep trick",
        "sleep hack",
        "sleep ritual",
        "insomnia trick",
        # Specific mechanisms
        "fall asleep trick",
        "deep sleep trick",
        "sleep protocol",
        # Time hooks
        "fall asleep in minutes",
        "bedtime ritual sleep",
        # Ingredient mechanisms
        "melatonin trick",
        "magnesium sleep trick",
    ],

    # -----------------------------------------------------------------------
    # BLOOD PRESSURE — "morning ritual blood pressure" is a proven angle
    # Hypertension supplements growing strongly
    # -----------------------------------------------------------------------
    "blood_pressure": [
        # Broad base
        "high blood pressure",
        "hypertension",
        # DR-filtered mechanisms
        "blood pressure trick",
        "blood pressure ritual",
        "blood pressure morning ritual",
        "lower blood pressure naturally",
        # Ingredient mechanisms
        "beet root blood pressure",
        "garlic blood pressure",
        "hibiscus blood pressure",
        # Brand/drug angle
        "lisinopril alternative",
        "blood pressure no medication",
        # Condition anchors
        "systolic pressure trick",
        "hypertension morning trick",
    ],

    # -----------------------------------------------------------------------
    # NEUROPATHY — Gustavo explicitly mentioned, nerve pain is growing fast
    # "neuropathy" + "trick/ritual" finds dedicated supplement advertisers
    # -----------------------------------------------------------------------
    "neuropathy": [
        # Broad base
        "neuropathy",
        "nerve pain",
        # DR-filtered mechanisms
        "neuropathy trick",
        "nerve pain trick",
        "neuropathy ritual",
        "peripheral neuropathy trick",
        # Symptom hooks
        "tingling feet trick",
        "numbness feet trick",
        "burning feet trick",
        # Ingredient mechanisms
        "alpha lipoic acid neuropathy",
        "b12 nerve pain",
        # Condition anchors
        "diabetic neuropathy trick",
        "nerve regeneration trick",
    ],

}


# ---------------------------------------------------------------------------
# Keyword utilities
# ---------------------------------------------------------------------------

def get_keywords_for_nicho(niche: str) -> list[str]:
    """Return base keyword list for a niche."""
    return KEYWORDS.get(niche, [])


def get_keywords_expanded(niche: str, max_words: int = 4) -> list[str]:
    """
    Return base keywords plus 4th-word qualifier variants.
    Only expands 2-word and 3-word base keywords.
    Use max_words=4 for the full Gustavo-style expansion.
    """
    base = KEYWORDS.get(niche, [])
    all_kw: list[str] = []
    seen: set[str] = set()
    for kw in base:
        for variant in generate_variants(kw, max_words=max_words):
            if variant not in seen:
                seen.add(variant)
                all_kw.append(variant)
    return all_kw


def get_all_keywords() -> list[str]:
    all_kw: set[str] = set()
    for kw_list in KEYWORDS.values():
        all_kw.update(kw_list)
    return sorted(all_kw)


def get_available_nichos() -> list[str]:
    return list(KEYWORDS.keys())
