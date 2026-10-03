"""
Training script for arXiv category classifier - Kaggle notebook version

This script should be copy-pasted into a Kaggle notebook with the arxiv dataset added.
It trains a TF-IDF + Logistic Regression (One-vs-Rest) model for multi-label
classification of research papers into arXiv categories.

Run this on Kaggle (with GPU enabled for faster computation) and download
the exported model files when complete.
"""

# ============================================================================
# Cell 1: Imports and Setup
# ============================================================================
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.multiclass import OneVsRestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score
import joblib
import warnings
import os

warnings.filterwarnings('ignore')
print("✓ All libraries imported successfully")

# ============================================================================
# Cell 2: Load and Explore the arXiv Dataset
# ============================================================================
print("Loading arXiv dataset...")
df = pd.read_csv('/kaggle/input/arxiv/arxiv.csv')

print(f"Dataset shape: {df.shape}")
print(f"Columns: {df.columns.tolist()}")
print(f"\nFirst row:")
print(df.iloc[0])
print(f"\nData types:")
print(df.dtypes)
print(f"\nMissing values:")
print(df.isnull().sum())

# ============================================================================
# Cell 3: Filter to Target Categories
# ============================================================================
print("\n" + "="*60)
print("Filtering to target arXiv categories")
print("="*60)

# Target categories - must match ARXIV_CATEGORIES in external_paper_service.py
target_categories = [
    'cs.LG', 'cs.AI', 'cs.CV', 'cs.CL', 'cs.RO',
    'cs.NE', 'cs.IR', 'cs.CR', 'stat.ML'
]

print(f"Target categories: {target_categories}")

# Check which papers have at least one target category
def has_target_category(cat_string):
    if pd.isna(cat_string):
        return False
    cats = str(cat_string).split()
    return any(c in target_categories for c in cats)

df_filtered = df[df['categories'].apply(has_target_category)].copy()
print(f"✓ Filtered from {len(df):,} to {len(df_filtered):,} papers")

# Create binary matrix: one column per category
print("\nCreating multi-label matrix...")
category_matrix = pd.DataFrame(index=df_filtered.index)
for cat in target_categories:
    category_matrix[cat] = df_filtered['categories'].apply(
        lambda x: 1 if pd.notna(x) and cat in str(x).split() else 0
    )

print("Category distribution:")
for cat in target_categories:
    count = category_matrix[cat].sum()
    pct = (count / len(category_matrix)) * 100
    print(f"  {cat:10s}: {count:7,d} papers ({pct:5.1f}%)")

# Check for multi-label papers
multi_label_count = (category_matrix.sum(axis=1) > 1).sum()
single_label_count = (category_matrix.sum(axis=1) == 1).sum()
print(f"\nLabel distribution:")
print(f"  Single-label papers: {single_label_count:,}")
print(f"  Multi-label papers:  {multi_label_count:,}")

# ============================================================================
# Cell 4: Prepare Features and Labels
# ============================================================================
print("\n" + "="*60)
print("Preparing training data")
print("="*60)

# Combine title and abstract
df_filtered['text'] = (
    df_filtered['title'].fillna('') + '\n' +
    df_filtered['abstract'].fillna('')
)

# Remove entries with very short text
min_text_len = 10
df_filtered = df_filtered[df_filtered['text'].str.len() > min_text_len]
category_matrix = category_matrix.loc[df_filtered.index]

X = df_filtered['text'].values
y = category_matrix.values

print(f"Training dataset: {len(X):,} papers")
print(f"Label matrix shape: {y.shape}")
print(f"Average text length: {X.astype(str).str.len().mean():.0f} characters")

# 80/20 train/test split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y.sum(axis=1) > 1
)

print(f"\nSplit:")
print(f"  Training set:   {len(X_train):,} papers")
print(f"  Test set:       {len(X_test):,} papers")

# ============================================================================
# Cell 5: Train TF-IDF Vectorizer
# ============================================================================
print("\n" + "="*60)
print("Training TF-IDF Vectorizer")
print("="*60)

vectorizer = TfidfVectorizer(
    max_features=5000,
    ngram_range=(1, 2),
    min_df=5,
    max_df=0.8,
    sublinear_tf=True,
    lowercase=True
)

print("Vectorizing training texts...")
X_train_vec = vectorizer.fit_transform(X_train)

print("Vectorizing test texts...")
X_test_vec = vectorizer.transform(X_test)

print(f"\nVectorizer details:")
print(f"  Feature matrix shape (train): {X_train_vec.shape}")
print(f"  Feature matrix shape (test):  {X_test_vec.shape}")
print(f"  Vocabulary size: {len(vectorizer.get_feature_names_out()):,}")
print(f"  Sparsity: {(1 - X_train_vec.nnz / (X_train_vec.shape[0] * X_train_vec.shape[1])) * 100:.1f}%")

# ============================================================================
# Cell 6: Train One-vs-Rest Logistic Regression
# ============================================================================
print("\n" + "="*60)
print("Training One-vs-Rest Logistic Regression")
print("="*60)

model = OneVsRestClassifier(
    LogisticRegression(
        max_iter=1000,
        random_state=42,
        n_jobs=-1,
        solver='lbfgs'
    ),
    n_jobs=-1
)

print("Training (this may take a few minutes)...")
model.fit(X_train_vec, y_train)
print("✓ Model training complete!")

# ============================================================================
# Cell 7: Evaluate on Test Set
# ============================================================================
print("\n" + "="*60)
print("EVALUATION RESULTS (Test Set)")
print("="*60)

y_pred = model.predict(X_test_vec)

print("\nPer-Category Metrics:")
print("-" * 60)
print(f"{'Category':<12} {'Precision':<12} {'Recall':<12} {'F1-Score':<12}")
print("-" * 60)

results = []
for i, cat in enumerate(target_categories):
    precision = precision_score(y_test[:, i], y_pred[:, i], zero_division=0)
    recall = recall_score(y_test[:, i], y_pred[:, i], zero_division=0)
    f1 = f1_score(y_test[:, i], y_pred[:, i], zero_division=0)
    
    print(f"{cat:<12} {precision:>11.3f} {recall:>11.3f} {f1:>11.3f}")
    results.append((cat, precision, recall, f1))

# Macro-average metrics
macro_precision = precision_score(y_test, y_pred, average='macro', zero_division=0)
macro_recall = recall_score(y_test, y_pred, average='macro', zero_division=0)
macro_f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)

print("-" * 60)
print(f"{'MACRO-AVG':<12} {macro_precision:>11.3f} {macro_recall:>11.3f} {macro_f1:>11.3f}")
print("-" * 60)

# ============================================================================
# Cell 8: Export Model and Vectorizer
# ============================================================================
print("\n" + "="*60)
print("Exporting Model and Vectorizer")
print("="*60)

output_dir = '/kaggle/working'
model_path = os.path.join(output_dir, 'category_classifier.joblib')
vectorizer_path = os.path.join(output_dir, 'category_vectorizer.joblib')

print(f"Saving model to {model_path}...")
joblib.dump(model, model_path, compress=3)

print(f"Saving vectorizer to {vectorizer_path}...")
joblib.dump(vectorizer, vectorizer_path, compress=3)

# Report file sizes
model_size = os.path.getsize(model_path) / (1024*1024)
vectorizer_size = os.path.getsize(vectorizer_path) / (1024*1024)

print(f"\n✓ Export complete!")
print(f"  Model size:      {model_size:.2f} MB")
print(f"  Vectorizer size: {vectorizer_size:.2f} MB")
print(f"  Total:           {model_size + vectorizer_size:.2f} MB")

# ============================================================================
# Cell 9: Save Evaluation Report
# ============================================================================
print("\n" + "="*60)
print("Saving Evaluation Report")
print("="*60)

report_path = os.path.join(output_dir, 'evaluation_report.txt')
with open(report_path, 'w') as f:
    f.write("ARXIV CATEGORY CLASSIFIER - EVALUATION REPORT\n")
    f.write("=" * 60 + "\n\n")
    
    f.write("Dataset:\n")
    f.write(f"  Training samples: {len(X_train):,}\n")
    f.write(f"  Test samples:     {len(X_test):,}\n")
    f.write(f"  Features:         {X_train_vec.shape[1]:,}\n")
    f.write(f"  Categories:       {len(target_categories)}\n\n")
    
    f.write("Per-Category Metrics:\n")
    f.write("-" * 60 + "\n")
    f.write(f"{'Category':<12} {'Precision':<12} {'Recall':<12} {'F1-Score':<12}\n")
    f.write("-" * 60 + "\n")
    for cat, p, r, f1 in results:
        f.write(f"{cat:<12} {p:>11.3f} {r:>11.3f} {f1:>11.3f}\n")
    f.write("-" * 60 + "\n")
    f.write(f"{'MACRO-AVG':<12} {macro_precision:>11.3f} {macro_recall:>11.3f} {macro_f1:>11.3f}\n")
    f.write("-" * 60 + "\n")

print(f"✓ Report saved to {report_path}")

# ============================================================================
# Cell 10: Verify Export and Test Predictions
# ============================================================================
print("\n" + "="*60)
print("Verifying Export")
print("="*60)

# Reload the model
print("Reloading model for verification...")
model_loaded = joblib.load(model_path)
vec_loaded = joblib.load(vectorizer_path)
print("✓ Models reloaded successfully")

# Test prediction on a sample paper
sample_title = "Attention Is All You Need"
sample_abstract = "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks in an encoder-decoder configuration. The best performing models also connect the encoder and decoder through an attention mechanism."

print(f"\nTest prediction:")
print(f"  Title: {sample_title}")
print(f"  Abstract: {sample_abstract[:80]}...\n")

text_vec = vec_loaded.transform([sample_title + "\n" + sample_abstract])
scores = model_loaded.decision_function(text_vec)[0]

predictions = [(cat, float(score)) for cat, score in zip(target_categories, scores)]
predictions.sort(key=lambda x: x[1], reverse=True)

print("  Predictions:")
for cat, score in predictions:
    print(f"    {cat}: {score:.3f}")

print("\n" + "="*60)
print("✓ All verification checks passed!")
print("="*60)
print("\nNext steps:")
print("1. Download the exported files from the Outputs section:")
print("   - category_classifier.joblib")
print("   - category_vectorizer.joblib")
print("   - evaluation_report.txt (optional)")
print("2. Place them in backend/ml_models/")
print("3. Update ml_models/README.md with the evaluation metrics above")
print("4. Test with: python -c \"from app.services.classification_service import predict_categories; print(predict_categories('...', '...'))\"")
