# ML Models: Paper Category Classifier

## Overview
This directory stores the trained category classifier model used in Phase 13+.

**Status**: ✅ **Model trained locally** (Phase 13 complete)

## Model Architecture
- **Type**: Multi-label classification
- **Input**: Paper title + abstract (text)
- **Output**: Predicted arXiv category codes + confidence scores (0-1)
- **Training algorithm**: TF-IDF + Logistic Regression (One-vs-Rest)
- **Categories**: 9 arXiv categories (cs.LG, cs.AI, cs.CV, cs.CL, cs.RO, cs.NE, cs.IR, cs.CR, stat.ML)

## Files
- `category_classifier.joblib` - Trained logistic regression model (One-vs-Rest)
- `category_vectorizer.joblib` - TF-IDF vectorizer for text preprocessing
- `training_notebook.ipynb` - Source Kaggle notebook (for reference)
- `evaluation_report.txt` - Precision/recall/F1 scores and macro-average from the held-out test set

## Setup: Train & Export the Model

### Step 1: Set up Kaggle API credentials
1. Log in to [Kaggle.com](https://www.kaggle.com)
2. Go to **Settings > API > Create New API Token**
3. This downloads `kaggle.json`
4. Place it in `~/.kaggle/kaggle.json` (Linux/Mac) or `%USERPROFILE%/.kaggle/kaggle.json` (Windows)
5. Ensure permissions: `chmod 600 ~/.kaggle/kaggle.json`

### Step 2: Create a Kaggle notebook
1. Go to [Kaggle Notebooks](https://www.kaggle.com/code)
2. Click **New Notebook**
3. Add the dataset: **Cornell University / arxiv** (search for it)
4. Copy the code from `training_script.py` into the notebook cells (see Step 3)
5. Run the notebook

### Step 3: Training script for Kaggle notebook
The Kaggle notebook should contain the following cells:

```python
# Cell 1: Imports
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.multiclass import OneVsRestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score, classification_report
import joblib
import warnings
warnings.filterwarnings('ignore')

# Cell 2: Load and explore the dataset
df = pd.read_csv('/kaggle/input/arxiv/arxiv.csv')
print("Dataset shape:", df.shape)
print("Columns:", df.columns.tolist())
print("\nFirst row:")
print(df.iloc[0])
print("\nSample categories:")
print(df['categories'].head(10))
```

```python
# Cell 3: Filter to the target categories
# Use only the 9 categories in ARXIV_CATEGORIES
target_categories = ['cs.LG', 'cs.AI', 'cs.CV', 'cs.CL', 'cs.RO', 'cs.NE', 'cs.IR', 'cs.CR', 'stat.ML']

# Parse multi-category strings and filter
def has_target_category(cat_string):
    if pd.isna(cat_string):
        return False
    cats = str(cat_string).split()
    return any(c in target_categories for c in cats)

df = df[df['categories'].apply(has_target_category)]
print(f"Filtered to {len(df)} papers with target categories")

# Create binary matrix: one column per category
category_matrix = pd.DataFrame()
for cat in target_categories:
    category_matrix[cat] = df['categories'].apply(
        lambda x: 1 if pd.notna(x) and cat in str(x) else 0
    )

print("\nCategory distribution:")
print(category_matrix.sum())
print("\nMulti-label examples (papers with >1 category):")
print(f"{(category_matrix.sum(axis=1) > 1).sum()} papers have multiple categories")
```

```python
# Cell 4: Prepare features and labels
# Combine title and abstract
df['text'] = df['title'].fillna('') + '\n' + df['abstract'].fillna('')

# Handle missing values
df = df[df['text'].str.len() > 10]  # Filter out very short entries
X = df['text'].values
y = category_matrix.values

print(f"Training set: {len(X)} papers")
print(f"Label matrix shape: {y.shape}")

# Split 80/20 train/test
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)
print(f"Train: {len(X_train)}, Test: {len(X_test)}")
```

```python
# Cell 5: Train TF-IDF vectorizer and vectorize texts
print("Training TF-IDF vectorizer...")
vectorizer = TfidfVectorizer(
    max_features=5000,
    ngram_range=(1, 2),
    min_df=5,
    max_df=0.8,
    sublinear_tf=True
)

X_train_vec = vectorizer.fit_transform(X_train)
X_test_vec = vectorizer.transform(X_test)

print(f"Feature matrix shape: {X_train_vec.shape}")
print(f"Vocabulary size: {len(vectorizer.get_feature_names_out())}")
```

```python
# Cell 6: Train One-vs-Rest logistic regression
print("Training One-vs-Rest logistic regression...")
model = OneVsRestClassifier(
    LogisticRegression(max_iter=1000, random_state=42, n_jobs=-1)
)
model.fit(X_train_vec, y_train)
print("Model trained!")
```

```python
# Cell 7: Evaluate on test set
print("Evaluating on test set...")
y_pred = model.predict(X_test_vec)

# Per-category metrics
print("\n" + "="*60)
print("Per-Category Metrics (Test Set)")
print("="*60)
for i, cat in enumerate(target_categories):
    precision = precision_score(y_test[:, i], y_pred[:, i], zero_division=0)
    recall = recall_score(y_test[:, i], y_pred[:, i], zero_division=0)
    f1 = f1_score(y_test[:, i], y_pred[:, i], zero_division=0)
    print(f"{cat:10s} | P: {precision:.3f} | R: {recall:.3f} | F1: {f1:.3f}")

# Macro-average metrics
macro_precision = precision_score(y_test, y_pred, average='macro', zero_division=0)
macro_recall = recall_score(y_test, y_pred, average='macro', zero_division=0)
macro_f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)

print("\n" + "="*60)
print("Macro-Averaged Metrics")
print("="*60)
print(f"Precision: {macro_precision:.3f}")
print(f"Recall:    {macro_recall:.3f}")
print(f"F1-Score:  {macro_f1:.3f}")
print("="*60)
```

```python
# Cell 8: Export the model and vectorizer
print("Exporting model and vectorizer...")
joblib.dump(model, 'category_classifier.joblib', compress=3)
joblib.dump(vectorizer, 'category_vectorizer.joblib', compress=3)
print("✓ Exported category_classifier.joblib")
print("✓ Exported category_vectorizer.joblib")

# Show file sizes
import os
size_model = os.path.getsize('category_classifier.joblib') / (1024*1024)
size_vec = os.path.getsize('category_vectorizer.joblib') / (1024*1024)
print(f"\nFile sizes:")
print(f"  Classifier: {size_model:.2f} MB")
print(f"  Vectorizer: {size_vec:.2f} MB")
```

### Step 4: Download the exported model
1. In the Kaggle notebook, click **Output** (right sidebar)
2. Download both files:
   - `category_classifier.joblib`
   - `category_vectorizer.joblib`
3. Place them in `backend/ml_models/`

### Step 5: Test the backend service
From `backend/`:
```bash
# Install dependencies (if not already done)
pip install -e .

# Test the service interactively (Python REPL or pytest)
from app.services.classification_service import predict_categories

result = predict_categories(
    title="Attention Is All You Need",
    abstract="The dominant sequence transduction models are based on complex recurrent..."
)
print(result)
# Expected output: [('cs.LG', 0.92), ('cs.CL', 0.78), ...] (or similar)
```

## Verification Checklist
- [ ] Model files exist: `category_classifier.joblib` and `category_vectorizer.joblib`
- [ ] Both files are < 50 MB (should be ~5-10 MB each)
- [ ] `predict_categories()` loads without errors
- [ ] Predictions on known papers roughly match their arXiv categories
- [ ] Evaluation metrics recorded in this file (see "Evaluation Results" section below)

## Evaluation Results
**Training completed on Phase 13 (local training with stratified sampling)**

Dataset:
- Original arXiv papers: 3,164,528
- Filtered to target categories: 686,235
- Training set (sampled): 80,000 papers (60% single-label, 40% multi-label)
- Test set (held-out): 20,000 papers
- Features: 5,000 TF-IDF dimensions

```
Per-Category Metrics (Test Set):
cs.LG      | P: 0.718 | R: 0.549 | F1: 0.622
cs.AI      | P: 0.812 | R: 0.508 | F1: 0.625
cs.CV      | P: 0.935 | R: 0.871 | F1: 0.902 ⭐ (best F1)
cs.CL      | P: 0.917 | R: 0.831 | F1: 0.872
cs.RO      | P: 0.916 | R: 0.701 | F1: 0.794
cs.NE      | P: 0.780 | R: 0.360 | F1: 0.492 (lowest recall)
cs.IR      | P: 0.800 | R: 0.495 | F1: 0.612
cs.CR      | P: 0.958 | R: 0.838 | F1: 0.894 ⭐ (best precision)
stat.ML    | P: 0.732 | R: 0.559 | F1: 0.634

Macro-Averaged Metrics:
Precision: 0.841
Recall:    0.633
F1-Score:  0.715
```

**Key Findings**:
- Strong performance on vision (cs.CV F1: 0.902) and security (cs.CR F1: 0.894) categories
- Solid NLP capability (cs.CL F1: 0.872)
- Lower recall on cs.NE (0.360) due to sparse training data (2.7% of filtered dataset)
- Macro-averaged F1 of 0.715 indicates balanced but not exceptional performance across categories
- Suitable for Phase 14 (recommendations) and Phase 15 (alerts) with reasonable confidence thresholds

## Troubleshooting

**Q: ModuleNotFoundError: No module named 'joblib'**
A: Install joblib: `pip install joblib`

**Q: FileNotFoundError: category_classifier.joblib not found**
A: The model hasn't been trained yet. Follow the setup steps above.

**Q: predict_categories() returns empty list**
A: Check the logs. Either the model files don't exist, or there was an error during vectorization. Verify file paths match your installation.

**Q: Model file is very large (>100 MB)**
A: This is fine; joblib files can be large. Compression in `joblib.dump(..., compress=3)` helps. If you're concerned about repo size, store the files outside git with a download script.

## Dependencies
- scikit-learn >= 1.0
- joblib >= 1.2
- pandas (for training only, not needed at runtime)
- numpy (for training only, not needed at runtime)

These are already listed in `backend/pyproject.toml`.

## References
- Dataset: https://www.kaggle.com/datasets/Cornell-University/arxiv
- scikit-learn One-vs-Rest: https://scikit-learn.org/stable/modules/generated/sklearn.multiclass.OneVsRestClassifier.html
- TF-IDF vectorizer: https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html
