"""
Phase 13 Local Training Runner

Downloads the arXiv dataset from Kaggle and trains the category classifier locally.
"""

import os
import sys
import subprocess
from pathlib import Path

# Setup paths
backend_dir = Path(__file__).parent
ml_models_dir = backend_dir / "ml_models"
data_dir = ml_models_dir / "data"
data_dir.mkdir(exist_ok=True)

print("="*70)
print("PHASE 13 - LOCAL MODEL TRAINING")
print("="*70)

# Step 1: Download dataset
print("\n[1/3] Downloading Cornell arXiv dataset from Kaggle...")
print("-" * 70)

dataset_name = "Cornell-University/arxiv"
csv_file = data_dir / "arxiv.csv"

if csv_file.exists():
    print(f"✓ Dataset already exists at {csv_file}")
    print(f"  Size: {csv_file.stat().st_size / (1024**3):.2f} GB")
else:
    print(f"Downloading {dataset_name}...")
    try:
        os.chdir(data_dir)
        result = subprocess.run(
            ["kaggle", "datasets", "download", "-d", dataset_name],
            capture_output=True,
            text=True,
            timeout=600  # 10 min timeout
        )
        
        if result.returncode != 0:
            print(f"❌ Download failed:")
            print(result.stderr)
            sys.exit(1)
        
        print("✓ Dataset downloaded")
        
        # Extract if needed
        zip_file = data_dir / f"{dataset_name.split('/')[-1]}.zip"
        if zip_file.exists():
            print("Extracting ZIP file...")
            subprocess.run(["powershell", "-Command", f"Expand-Archive '{zip_file}' '{data_dir}' -Force"], check=True)
            zip_file.unlink()
            print("✓ Extracted")
        
        if not csv_file.exists():
            print("❌ CSV file not found after download")
            sys.exit(1)
        
        print(f"✓ Dataset ready at {csv_file}")
        
    except Exception as e:
        print(f"❌ Error downloading dataset: {e}")
        sys.exit(1)

# Step 2: Run training script
print("\n[2/3] Training model (this will take 2-5 minutes)...")
print("-" * 70)

training_script = backend_dir / "ml_models" / "training_script_local.py"
os.chdir(backend_dir)

try:
    result = subprocess.run(
        [sys.executable, str(training_script), str(data_dir / "arxiv.csv")],
        timeout=600  # 10 min timeout
    )
    
    if result.returncode != 0:
        print("❌ Training failed")
        sys.exit(1)
    
except subprocess.TimeoutExpired:
    print("❌ Training timeout (exceeded 10 minutes)")
    sys.exit(1)

# Step 3: Verify
print("\n[3/3] Verifying trained model...")
print("-" * 70)

os.chdir(backend_dir)

try:
    result = subprocess.run(
        [sys.executable, "verify_classification.py"],
        timeout=60
    )
    
    if result.returncode != 0:
        print("⚠ Verification failed - model may need retraining")
        sys.exit(1)
    
except subprocess.TimeoutExpired:
    print("❌ Verification timeout")
    sys.exit(1)

print("\n" + "="*70)
print("✅ PHASE 13 COMPLETE - MODEL TRAINED AND VERIFIED")
print("="*70)
print("\nNext steps:")
print("1. Review evaluation metrics in ml_models/README.md")
print("2. Start Phase 14 (Personalized Recommendations)")
print("3. Start Phase 15 (In-app Alerts)")
