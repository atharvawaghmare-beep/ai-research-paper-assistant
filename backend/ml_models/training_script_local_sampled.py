"""
Training script for arXiv category classifier - LOCAL version (Memory-efficient)

This script trains a TF-IDF + Logistic Regression (One-vs-Rest) model
for multi-label classification of research papers into arXiv categories.

Uses stratified sampling to handle large datasets on memory-constrained systems.

Usage:
    python ml_models/training_script_local_sampled.py <path_to_arxiv_csv>

Example:
    python ml_models/training_script_local_sampled.py ml_models/data/arxiv.csv
"""

import sys
import os
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.multiclass import OneVsRestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score
import joblib
import warnings

warnings.filterwarnings('ignore')

# ============================================================================
# Setup
# ============================================================================
if len(sys.argv) < 2:
    print("Usage: python training_script_local_sampled.py <path_to_arxiv_csv>")
    print("Example: python training_script_local_sampled.py ml_models/data/arxiv.csv")
    sys.exit(1)

csv_path = sys.argv[1]

if not os.path.exists(csv_path):
    print(f"❌ File not found: {csv_path}")
    sys.exit(1)

print("="*70)
print("TRAINING ARXIV CATEGORY CLASSIFIER (LOCAL - MEMORY-EFFICIENT)")
print("="*70)
print(f"\nDataset: {csv_path}")
print(f"File size: {os.path.getsize(csv_path) / (1024**3):.2f} GB")

# Target categories
target_categories = [
    'cs.LG', 'cs.AI', 'cs.CV', 'cs.CL', 'cs.RO',
    'cs.NE', 'cs.IR', 'cs.CR', 'stat.ML'
]

output_dir = os.path.dirname(csv_path)  # Save models in same dir as dataset

# ============================================================================
# Load and Filter Dataset (with sampling)
# ============================================================================
print("\n[1/7] Loading dataset...")

# Load in chunks to reduce memory usage
chunksize = 50000
chunks = []

for i, chunk in enumerate(pd.read_csv(csv_path, chunksize=chunksize)):
    if i == 0:
        print(f"  Reading in {chunksize:,} record chunks...")
    
    # Filter to target categories
    def has_target_category(cat_string):
        if pd.isna(cat_string):
            return False
        cats = str(cat_string).split()
        return any(c in target_categories for c in cats)
    
    chunk = chunk[chunk['categories'].apply(has_target_category)].copy()
    chunks.append(chunk)
    
    if (i + 1) % 10 == 0:
        total_so_far = sum(len(c) for c in chunks)
        print(f"  Processed {(i+1)*chunksize:,} rows, filtered {total_so_far:,} matches so far...")

df_filtered = pd.concat(chunks, ignore_index=True)
print(f"  Total papers: 3,164,528")
print(f"  Filtered to: {len(df_filtered):,} papers with target categories")

# Sample for training (to fit in memory)
# Use stratified sampling based on multi-label ratio
sample_size = min(100000, len(df_filtered))  # Cap at 100k for reasonable training time
print(f"\n  Sampling {sample_size:,} papers for training (from {len(df_filtered):,} total)...")

# Mark single vs multi-label
is_multi = df_filtered['categories'].apply(lambda x: len(str(x).split()) > 1)

# Stratified sample
sample_idx = []
multi_count = 0
single_count = 0
multi_target = int(sample_size * 0.4)  # 40% multi-label
single_target = sample_size - multi_target  # 60% single-label

for idx, is_m in is_multi.items():
    if is_m and multi_count < multi_target:
        sample_idx.append(idx)
        multi_count += 1
    elif not is_m and single_count < single_target:
        sample_idx.append(idx)
        single_count += 1
    
    if len(sample_idx) >= sample_size:
        break

df_filtered = df_filtered.loc[sample_idx].reset_index(drop=True)
print(f"  Final training set: {len(df_filtered):,} papers")
print(f"    Multi-label: {multi_count:,}")
print(f"    Single-label: {single_count:,}")

# ============================================================================
# Prepare Labels
# ============================================================================
print("\n[2/7] Preparing labels...")

category_matrix = pd.DataFrame(index=df_filtered.index)
for cat in target_categories:
    category_matrix[cat] = df_filtered['categories'].apply(
        lambda x: 1 if pd.notna(x) and cat in str(x).split() else 0
    )

print("  Category distribution:")
for cat in target_categories:
    count = category_matrix[cat].sum()
    pct = (count / len(category_matrix)) * 100
    print(f"    {cat:10s}: {count:7,d} ({pct:5.1f}%)")

# ============================================================================
# Prepare Features
# ============================================================================
print("\n[3/7] Preparing features...")

df_filtered['text'] = (
    df_filtered['title'].fillna('') + '\n' +
    df_filtered['abstract'].fillna('')
)

# Remove very short entries
df_filtered = df_filtered[df_filtered['text'].str.len() > 10]
category_matrix = category_matrix.loc[df_filtered.index]

X = df_filtered['text'].values
y = category_matrix.values

print(f"  Total samples: {len(X):,}")

# Split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y.sum(axis=1) > 1
)

print(f"  Train split: {len(X_train):,}")
print(f"  Test split:  {len(X_test):,}")

# ============================================================================
# Train Vectorizer
# ============================================================================
print("\n[4/7] Training TF-IDF vectorizer...")

vectorizer = TfidfVectorizer(
    max_features=5000,
    ngram_range=(1, 2),
    min_df=5,
    max_df=0.8,
    sublinear_tf=True,
    lowercase=True
)

X_train_vec = vectorizer.fit_transform(X_train)
X_test_vec = vectorizer.transform(X_test)

print(f"  Feature matrix shape: {X_train_vec.shape}")
print(f"  Vocabulary size: {len(vectorizer.get_feature_names_out()):,}")
print(f"  Sparsity: {(1 - X_train_vec.nnz / (X_train_vec.shape[0] * X_train_vec.shape[1])) * 100:.1f}%")

# ============================================================================
# Train Model
# ============================================================================
print("\n[5/7] Training One-vs-Rest logistic regression...")

model = OneVsRestClassifier(
    LogisticRegression(
        max_iter=1000,
        random_state=42,
        n_jobs=-1,
        solver='lbfgs'
    ),
    n_jobs=-1
)

model.fit(X_train_vec, y_train)
print("  ✓ Model training complete")

# ============================================================================
# Evaluate
# ============================================================================
print("\n[6/7] Evaluating on test set...")

y_pred = model.predict(X_test_vec)

print("\n  Per-Category Metrics:")
print("  " + "-"*60)
print(f"  {'Category':<12} {'Precision':<12} {'Recall':<12} {'F1-Score':<12}")
print("  " + "-"*60)

results = []
for i, cat in enumerate(target_categories):
    precision = precision_score(y_test[:, i], y_pred[:, i], zero_division=0)
    recall = recall_score(y_test[:, i], y_pred[:, i], zero_division=0)
    f1 = f1_score(y_test[:, i], y_pred[:, i], zero_division=0)
    
    print(f"  {cat:<12} {precision:>11.3f} {recall:>11.3f} {f1:>11.3f}")
    results.append((cat, precision, recall, f1))

macro_precision = precision_score(y_test, y_pred, average='macro', zero_division=0)
macro_recall = recall_score(y_test, y_pred, average='macro', zero_division=0)
macro_f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)

print("  " + "-"*60)
print(f"  {'MACRO-AVG':<12} {macro_precision:>11.3f} {macro_recall:>11.3f} {macro_f1:>11.3f}")
print("  " + "-"*60)

# ============================================================================
# Export
# ============================================================================
print("\n[7/7] Exporting model and vectorizer...")

# Save in parent directory (backend/ml_models/)
parent_dir = os.path.dirname(output_dir)
model_path = os.path.join(parent_dir, 'category_classifier.joblib')
vectorizer_path = os.path.join(parent_dir, 'category_vectorizer.joblib')

joblib.dump(model, model_path, compress=3)
joblib.dump(vectorizer, vectorizer_path, compress=3)

model_size = os.path.getsize(model_path) / (1024*1024)
vectorizer_size = os.path.getsize(vectorizer_path) / (1024*1024)

print(f"  ✓ Saved: {model_path}")
print(f"    Size: {model_size:.2f} MB")
print(f"  ✓ Saved: {vectorizer_path}")
print(f"    Size: {vectorizer_size:.2f} MB")
print(f"  Total: {model_size + vectorizer_size:.2f} MB")

# ============================================================================
# Save Evaluation Report
# ============================================================================
report_path = os.path.join(parent_dir, 'evaluation_report.txt')
with open(report_path, 'w') as f:
    f.write("ARXIV CATEGORY CLASSIFIER - EVALUATION REPORT\n")
    f.write("=" * 60 + "\n\n")
    
    f.write("Dataset (Sampled):\n")
    f.write(f"  Original papers: 3,164,528\n")
    f.write(f"  With target categories: 686,235\n")
    f.write(f"  Training set sample: {len(X_train):,}\n")
    f.write(f"  Test set sample: {len(X_test):,}\n")
    f.write(f"  Features: {X_train_vec.shape[1]:,}\n")
    f.write(f"  Categories: {len(target_categories)}\n\n")
    
    f.write("Per-Category Metrics:\n")
    f.write("-" * 60 + "\n")
    f.write(f"{'Category':<12} {'Precision':<12} {'Recall':<12} {'F1-Score':<12}\n")
    f.write("-" * 60 + "\n")
    for cat, p, r, f1 in results:
        f.write(f"{cat:<12} {p:>11.3f} {r:>11.3f} {f1:>11.3f}\n")
    f.write("-" * 60 + "\n")
    f.write(f"{'MACRO-AVG':<12} {macro_precision:>11.3f} {macro_recall:>11.3f} {macro_f1:>11.3f}\n")
    f.write("-" * 60 + "\n")

print(f"  ✓ Report: {report_path}")

# ============================================================================
# Summary
# ============================================================================
print("\n" + "="*70)
print("✅ TRAINING COMPLETE")
print("="*70)
print(f"\nModel files:")
print(f"  {model_path}")
print(f"  {vectorizer_path}")
print(f"\nEvaluation metrics:")
print(f"  Precision: {macro_precision:.3f}")
print(f"  Recall:    {macro_recall:.3f}")
print(f"  F1-Score:  {macro_f1:.3f}")
print(f"\nReport saved to:")
print(f"  {report_path}")
print("\n" + "="*70)
