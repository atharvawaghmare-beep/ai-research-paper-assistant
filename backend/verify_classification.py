"""
Phase 13 Verification Script

This script tests the classification service after the model has been trained
and exported. Run this after you've downloaded the model files and placed them
in backend/ml_models/.

Usage:
    python verify_classification.py
"""

import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.services.classification_service import predict_categories


def test_predict_categories():
    """Test the predict_categories function with known papers."""
    
    print("="*70)
    print("CLASSIFICATION SERVICE VERIFICATION")
    print("="*70)
    
    # Test cases: (title, abstract, expected_top_category)
    test_cases = [
        (
            "Attention Is All You Need",
            "The dominant sequence transduction models are based on complex recurrent "
            "or convolutional neural networks in an encoder-decoder configuration. "
            "The best performing models also connect the encoder and decoder through "
            "an attention mechanism. We propose a new simple network architecture, "
            "the Transformer, based solely on attention mechanisms, dispensing with "
            "recurrence and convolutions entirely.",
            "cs.LG"  # Expected: Machine Learning
        ),
        (
            "A Convolutional Neural Network for Modelling Sentences",
            "The ability to accurately represent sentences is central to language understanding. "
            "We describe a convolutional architecture for sentence-level classification tasks. "
            "The model employs a single layer of convolution built on top of word vectors "
            "obtained from an unsupervised neural language model.",
            "cs.CL"  # Expected: Computation and Language (NLP)
        ),
        (
            "Deep Residual Learning for Image Recognition",
            "Deep neural networks are difficult to train. We present a residual learning framework "
            "to ease the training of networks that are substantially deeper than those used previously. "
            "We explicitly reformulate the layers as learning residual functions with reference to the "
            "layer inputs, instead of learning unreferenced functions. We provide comprehensive empirical "
            "evidence showing that these residual networks are easier to optimize, and can gain accuracy "
            "from considerably increased depth.",
            "cs.CV"  # Expected: Computer Vision
        ),
    ]
    
    all_passed = True
    
    for i, (title, abstract, expected_category) in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"Test Case {i}: {title[:50]}...")
        print(f"Expected top category: {expected_category}")
        print(f"{'='*70}")
        
        try:
            predictions = predict_categories(title, abstract, threshold=0.0)
            
            if not predictions:
                print("FAILED: No predictions returned")
                print("   Check that model files exist in backend/ml_models/")
                all_passed = False
                continue
            
            print(f"\nPredictions (sorted by confidence):")
            for rank, (category, score) in enumerate(predictions[:5], 1):
                marker = "TOP" if rank == 1 else "  "
                print(f"  {marker} {rank}. {category:10s} {score:>7.3f}")

            if any(score < 0 or score > 1 for _, score in predictions):
                print("FAILED: Prediction scores are outside the 0-1 probability range")
                all_passed = False
            
            top_category, top_score = predictions[0]
            
            # Check if the top prediction matches expected category
            if top_category == expected_category:
                print(f"\nPASS: Top prediction matches expected category")
                # Also check confidence is reasonable
                if top_score > 0.3:
                    print(f"PASS: Confidence score is reasonable ({top_score:.3f})")
                else:
                    print(f"WARNING: Confidence score is low ({top_score:.3f})")
                    print("  This might indicate the model needs retraining")
            else:
                print(f"\nPARTIAL: Top prediction ({top_category}) differs from expected ({expected_category})")
                print(f"  This is OK if the expected category is present in top 3-5 predictions:")
                top_categories = [cat for cat, _ in predictions[:5]]
                if expected_category in top_categories:
                    expected_rank = top_categories.index(expected_category) + 1
                    print(f"  {expected_category} found at rank {expected_rank}")
                else:
                    print(f"  {expected_category} NOT in top 5 predictions")
                    all_passed = False
        
        except Exception as e:
            print(f"FAILED: Exception during prediction")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False

    threshold_predictions = predict_categories(
        test_cases[1][0], test_cases[1][1], threshold=0.9
    )
    if threshold_predictions and all(score >= 0.9 for _, score in threshold_predictions):
        print("\nPASS: Confidence threshold filtering works")
    else:
        print("\nFAILED: Confidence threshold filtering is incorrect")
        all_passed = False
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    
    if all_passed:
        print("All tests PASSED")
        print("\nThe classification service is working correctly.")
        print("Phase 13 classifier verification complete.")
        return 0
    else:
        print("Some tests did not pass as expected")
        print("\nPossible issues:")
        print("  1. Model files not found in backend/ml_models/")
        print("  2. Model files corrupted or incorrectly formatted")
        print("  3. Training data was insufficient (train on Kaggle with more samples)")
        print("\nNext steps:")
        print("  1. Verify files exist:")
        print("     - backend/ml_models/category_classifier.joblib")
        print("     - backend/ml_models/category_vectorizer.joblib")
        print("  2. Check the Kaggle notebook training script")
        print("  3. Re-run the training on Kaggle and re-download the files")
        return 1


if __name__ == "__main__":
    exit_code = test_predict_categories()
    sys.exit(exit_code)
