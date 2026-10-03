"""
Service for paper category classification.

Uses a pre-trained TF-IDF + logistic regression model trained on the Cornell University
arXiv metadata dataset to predict arXiv categories for research papers based on title
and abstract.

The model must be exported as a joblib pickle and placed in `backend/ml_models/`.
See ml_models/README.md for training and export instructions.
"""

import os
import logging
from pathlib import Path
from typing import Optional

try:
    import joblib
except ImportError:
    joblib = None

logger = logging.getLogger(__name__)

# Category constants - must match ARXIV_CATEGORIES in external_paper_service.py
ARXIV_CATEGORIES = {
    "cs.LG": "Machine Learning",
    "cs.AI": "Artificial Intelligence",
    "cs.CV": "Computer Vision",
    "cs.CL": "Computation and Language (NLP)",
    "cs.RO": "Robotics",
    "cs.NE": "Neural and Evolutionary Computing",
    "cs.IR": "Information Retrieval",
    "cs.CR": "Cryptography and Security",
    "stat.ML": "Statistics - Machine Learning",
}


class ClassificationModel:
    """Loads and manages the category classification model."""

    def __init__(self):
        """Initialize the classification model.
        
        Attempts to load the model from `backend/ml_models/category_classifier.joblib`.
        If loading fails or the file doesn't exist, sets the model to None and logs a warning.
        The model can be used conditionally later.
        """
        self.model = None
        self.vectorizer = None
        self.categories = list(ARXIV_CATEGORIES.keys())
        self._load_model()

    def _load_model(self):
        """Load the trained model and vectorizer from disk."""
        if joblib is None:
            logger.warning("joblib not installed; category classification unavailable")
            return

        model_dir = Path(__file__).parent.parent.parent / "ml_models"
        model_path = model_dir / "category_classifier.joblib"
        vectorizer_path = model_dir / "category_vectorizer.joblib"

        if not model_path.exists():
            logger.warning(
                f"Model file not found at {model_path}. "
                "Category classification unavailable until model is trained and exported. "
                "See ml_models/README.md for instructions."
            )
            return

        if not vectorizer_path.exists():
            logger.warning(
                f"Vectorizer file not found at {vectorizer_path}. "
                "Both model and vectorizer must be exported together."
            )
            return

        try:
            self.model = joblib.load(model_path)
            self.vectorizer = joblib.load(vectorizer_path)
            logger.info(
                f"Loaded category classification model from {model_path}. "
                f"Categories: {', '.join(self.categories)}"
            )
        except Exception as e:
            logger.error(f"Failed to load model from {model_path}: {e}")
            self.model = None
            self.vectorizer = None

    def predict_categories(
        self,
        title: str,
        abstract: str,
        threshold: float = 0.3,
    ) -> list[tuple[str, float]]:
        """Predict arXiv categories for a paper.

        Args:
            title: Paper title.
            abstract: Paper abstract.
            threshold: Confidence threshold (0-1) for inclusion in results.
                       Predictions below this are excluded.
                       Default: 0.3

        Returns:
            List of (category_code, confidence_score) tuples, sorted by score descending.
            Empty list if the model is not loaded or prediction fails.

        Example:
            >>> svc.predict_categories(
            ...     "Attention Is All You Need",
            ...     "The dominant sequence transduction models are based on complex recurrent..."
            ... )
            [('cs.LG', 0.92), ('cs.CL', 0.78), ('stat.ML', 0.45)]

        """
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")

        if self.model is None or self.vectorizer is None:
            logger.debug(
                "Classification model not available; returning empty predictions. "
                "Ensure ml_models/ contains category_classifier.joblib and "
                "category_vectorizer.joblib"
            )
            return []

        try:
            # Combine title and abstract for feature extraction
            text = f"{title}\n{abstract}"

            # Vectorize the input text using the stored vectorizer
            features = self.vectorizer.transform([text])

            # One-vs-Rest logistic regression exposes per-category probabilities,
            # which match the public 0-1 confidence contract.
            scores = self.model.predict_proba(features)[0]

            # Pair each category with its confidence score
            predictions = list(zip(self.categories, scores))

            predictions = [
                (cat, float(score))
                for cat, score in predictions
                if score >= threshold
            ]
            predictions.sort(key=lambda x: x[1], reverse=True)
            return predictions

        except Exception as e:
            logger.error(f"Error during category prediction: {e}", exc_info=True)
            return []


# Global instance - loaded once at app startup
_classification_model: Optional[ClassificationModel] = None


def get_classification_service() -> ClassificationModel:
    """Get the global classification service instance.
    
    Called once per FastAPI app startup to initialize the model.
    Later requests reuse this singleton.
    """
    global _classification_model
    if _classification_model is None:
        _classification_model = ClassificationModel()
    return _classification_model


def predict_categories(
    title: str,
    abstract: str,
    threshold: float = 0.3,
) -> list[tuple[str, float]]:
    """Convenience function to predict categories via the global service.

    Args:
        title: Paper title.
        abstract: Paper abstract.
        threshold: Confidence threshold (0-1). Default: 0.3

    Returns:
        List of (category_code, confidence_score) tuples, sorted by score descending.
    """
    svc = get_classification_service()
    return svc.predict_categories(title, abstract, threshold=threshold)
