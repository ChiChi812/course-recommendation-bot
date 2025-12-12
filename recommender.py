# recommender.py
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Course:
    title: str
    organization: str
    certificate_type: str
    rating: float
    difficulty: str
    students_enrolled: float


def _convert_to_number(x):
    """
    Converts strings like '5.3k', '1.2M', '800', '-', 'N/A' into floats.
    """
    if pd.isna(x):
        return 0.0
    s = str(x).strip().lower().replace(",", "")
    try:
        if s.endswith("k"):
            return float(s[:-1]) * 1_000
        if s.endswith("m"):
            return float(s[:-1]) * 1_000_000
        if s in {"", "-", "n/a", "none"}:
            return 0.0
        return float(s)
    except Exception:
        return 0.0


class CourseRecommender:
    """
    Content-based TF-IDF similarity on title + org + certificate + difficulty.
    Re-ranks with a light popularity prior (rating + log(learners)).
    """
    def __init__(self, csv_path: str):
        df = pd.read_csv(csv_path)
        df.columns = [c.strip().lower() for c in df.columns]

        # Map your actual column names to internal ones
        rename = {
            "course_title": "title",
            "course_organization": "organization",
            "course_certificate_type": "certificate_type",
            "course_difficulty": "difficulty",
            "course_rating": "rating",
            "course_students_enrolled": "students_enrolled",
        }
        df = df.rename(columns=rename)

        # Ensure required columns exist
        for col in ["title", "organization", "certificate_type", "difficulty"]:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("")

        # Numbers
        df["rating"] = pd.to_numeric(df.get("rating", 0), errors="coerce").fillna(0.0)
        if "students_enrolled" not in df.columns:
            df["students_enrolled"] = 0.0
        df["students_enrolled"] = df["students_enrolled"].apply(_convert_to_number)

        # Text field for TF-IDF
        df["__text__"] = (
            df["title"].astype(str)
            + " "
            + df["organization"].astype(str)
            + " "
            + df["certificate_type"].astype(str)
            + " "
            + df["difficulty"].astype(str)
        )

        # Vectorize
        self.vectorizer = TfidfVectorizer(stop_words="english", min_df=2, ngram_range=(1, 2))
        self.tfidf = self.vectorizer.fit_transform(df["__text__"])

        # Popularity prior
        pop = 0.7 * df["rating"].astype(float) + 0.3 * np.log1p(df["students_enrolled"].astype(float))
        # normalize to 0..1 to mix with cosine
        pop = (pop - pop.min()) / (pop.max() - pop.min() + 1e-9)
        df["__pop__"] = pop

        self.df = df

    def _row_to_course(self, r: pd.Series) -> Course:
        return Course(
            title=str(r["title"]),
            organization=str(r["organization"]),
            certificate_type=str(r["certificate_type"]),
            rating=float(r["rating"]),
            difficulty=str(r["difficulty"]),
            students_enrolled=float(r["students_enrolled"]),
        )

    def recommend(self, query: str, top_k: int = 5) -> List[Course]:
        if not query or not query.strip():
            return self.trending(top_k=top_k)

        q = self.vectorizer.transform([query])
        sim = cosine_similarity(self.tfidf, q).ravel()

        score = 0.85 * sim + 0.15 * self.df["__pop__"].values
        top_idx = score.argsort()[::-1][:top_k]
        return [self._row_to_course(self.df.iloc[i]) for i in top_idx]

    def trending(self, top_k: int = 5) -> List[Course]:
        top = self.df.sort_values("__pop__", ascending=False).head(top_k)
        return [self._row_to_course(r) for _, r in top.iterrows()]
