# Phase 13: Quick Start - Train & Export Category Classifier

## TL;DR
1. Go to Kaggle, create notebook, add "Cornell-University/arxiv" dataset
2. Copy code from `backend/ml_models/training_script.py` into notebook (cells 1-10)
3. Run (2-5 mins with GPU), download `category_classifier.joblib` & `category_vectorizer.joblib`
4. Save to `backend/ml_models/`
5. Run `python backend/verify_classification.py` ✓

## What Was Built

### Code Ready to Use
- **`backend/app/services/classification_service.py`** - Inference service
  - Loads model at app startup
  - Function: `predict_categories(title, abstract) -> [(category, score), ...]`
  - Returns empty list if model not found (graceful degradation)

- **`backend/ml_models/training_script.py`** - Ready to paste into Kaggle
  - 10 cells, copy-paste ready
  - Trains TF-IDF + Logistic Regression on arXiv data
  - Tests on 20% hold-out, reports metrics
  - Exports model + vectorizer as joblib

- **`backend/ml_models/README.md`** - Complete setup guide
  - Step-by-step Kaggle setup
  - All Python code for cells
  - Troubleshooting section

- **`backend/verify_classification.py`** - Local testing
  - Tests on 3 known papers (Attention, CNN, ResNet)
  - Confirms predictions roughly match expected categories
  - Pass/fail checklist

### Dependencies Added
```
scikit-learn>=1.3,<2.0
joblib>=1.3,<2.0
```

## The Model

**Algorithm**: TF-IDF vectorizer + Logistic Regression (One-vs-Rest classifier)

**Why this baseline?**
- Fast: 2-5 mins training on Kaggle GPU
- Explainable: Clear feature weights per category
- Sufficient: ~80% macro F1 is enough for Phase 14/15
- Small: ~10 MB model (not 100+ MB like transformers)
- Easy: Only scikit-learn, already in requirements

**Categories** (9 total):
- cs.LG, cs.AI, cs.CV, cs.CL, cs.RO, cs.NE, cs.IR, cs.CR, stat.ML

**Training data**: Cornell arXiv dataset (~2.2M papers, filtered to ~500k with target categories)

## How to Train

### 1. Kaggle Setup (first time only)
```bash
# Download kaggle API key from https://www.kaggle.com/settings/account
# Put it in ~/.kaggle/kaggle.json (Linux/Mac) or %USERPROFILE%/.kaggle/kaggle.json (Windows)
# chmod 600 ~/.kaggle/kaggle.json (Linux/Mac only)
```

### 2. Create Kaggle Notebook
```
1. https://www.kaggle.com/code → New Notebook
2. Search & add dataset: "Cornell-University/arxiv"
3. Copy code from backend/ml_models/training_script.py
4. Split into 10 cells (see comments in script)
5. Run (enable GPU: Accelerator = "GPU" in settings)
6. ~2-5 minutes
```

### 3. Download & Test
```bash
# Download from Kaggle notebook Output section:
# - category_classifier.joblib
# - category_vectorizer.joblib
# - evaluation_report.txt (optional)

# Save to backend/ml_models/

# From backend/ directory:
cd backend
pip install -e .  # Install updated deps
python verify_classification.py
```

Expected output:
```
Test Case 1: Attention Is All You Need...
Expected top category: cs.LG
✓ TOP 1. cs.LG     0.92
✓ PASS: Top prediction matches expected category
```

### 4. Record Metrics
Copy the evaluation metrics from Kaggle notebook output into `backend/ml_models/README.md`:
```markdown
## Evaluation Results

Per-Category Metrics (Test Set):
cs.LG      | P: 0.85 | R: 0.78 | F1: 0.81
cs.AI      | P: 0.80 | R: 0.72 | F1: 0.76
...

Macro-Averaged Metrics:
Precision: 0.82
Recall:    0.75
F1-Score:  0.78
```

## Testing the Service (Before Model Training)

```python
from app.services.classification_service import predict_categories

# Before training - returns empty list (logged warning)
result = predict_categories("Sample title", "Sample abstract")
# → []

# After training - returns predictions
result = predict_categories("Attention Is All You Need", "The dominant sequence...")
# → [('cs.LG', 0.92), ('cs.CL', 0.78), ('stat.ML', 0.45)]
```

## Files Overview

```
backend/
├── ml_models/
│   ├── README.md                          ← Detailed setup guide
│   ├── training_script.py                 ← Copy to Kaggle notebook
│   ├── category_classifier.joblib         ← (After training)
│   └── category_vectorizer.joblib         ← (After training)
├── app/services/
│   └── classification_service.py           ← New inference service
├── verify_classification.py                ← Local verification
└── pyproject.toml                          ← (Updated: added scikit-learn, joblib)

PHASE_13_GUIDE.md                           ← Full implementation details
PHASE_13_QUICK_START.md                     ← This file
```

## What Happens Next

**Phase 14 (Personalized Recommendations):**
- Calls `predict_categories()` on recent arXiv papers
- Scores papers against user's library categories
- Returns top matches the user doesn't have

**Phase 15 (In-app Alerts):**
- Background job checks new arXiv papers periodically
- Calls `predict_categories()` on each
- Creates notifications for papers in user's interest categories

Both depend on this Phase 13 model working correctly.

## Troubleshooting

**Q: Where do I get the Kaggle API key?**
A: https://www.kaggle.com/settings/account → API → Create New Token

**Q: The notebook won't find the dataset**
A: Make sure you search for "Cornell-University/arxiv" and add it (not "arxiv" alone)

**Q: Training is very slow**
A: Enable GPU in notebook settings (Accelerator dropdown)

**Q: Model files are huge (>100 MB)**
A: That's OK if using compression. Check joblib.dump(..., compress=3)

**Q: `predict_categories()` returns empty list after downloading files**
A: Check:
- Files are in `backend/ml_models/`
- Filenames are exact: `category_classifier.joblib`, `category_vectorizer.joblib`
- Run `python verify_classification.py` for detailed error logs

**Q: Predictions don't match expected categories**
A: Possibilities:
- Training data needs filtering adjustment (Cell 3 of training_script.py)
- Vectorizer settings need tuning (Cell 5: max_features, ngram_range)
- Try with more training samples (arXiv has 2.2M papers)
- Class imbalance (some categories rarer than others)

## Gotchas

❌ **Don't** hardcode model path - use `Path(__file__).parent.parent / "ml_models"`
❌ **Don't** forget to export both model AND vectorizer (they go together)
❌ **Don't** skip verify_classification.py step (catches problems early)
✅ **Do** enable GPU in Kaggle notebook settings
✅ **Do** copy eval metrics to ml_models/README.md
✅ **Do** commit the training script and README, but .gitkeep for model files

## Status

- ✅ Backend code ready
- ✅ Training script ready
- ⏳ Awaiting Kaggle training
- ⏳ Model files to be downloaded
- ⏳ Phase 14 & 15 blocked until model is ready

---

**Total time to complete Phase 13:**
- Setup on Kaggle: 5 mins
- Training: 2-5 mins (with GPU)
- Download & test: 5 mins
- **Total: ~15 mins** (mostly waiting for training)

**Then ready for Phase 14 & 15** ✓
