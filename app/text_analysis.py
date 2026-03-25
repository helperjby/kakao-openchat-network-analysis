"""
텍스트 분석 모듈
- 한국어 형태소 분석 (kiwipiepy)
- 유저별 WordCloud 생성
- TF-IDF (유저별/커뮤니티별 특징 단어)
- LDA 토픽 모델링 (월별 추이 포함)
- 감성 분석 (KNU 감성사전 + Gemini 보정)
"""

import json
import os
import pickle
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from kiwipiepy import Kiwi
from wordcloud import WordCloud
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation

from app.config import (
    CACHE_DIR, GEMINI_API_KEY, GEMINI_MODEL,
    ANALYSIS_START_MS, ANALYSIS_END_MS,
)

# ── 상수 ──────────────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9))
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
SENTIMENT_DICT_PATH = str(Path(__file__).resolve().parent.parent / "data" / "knu_sentiment.json")
WORDCLOUD_DIR = os.path.join(CACHE_DIR, "wordclouds")

# 한국어 불용어
STOPWORDS_KO = {
    "것", "수", "나", "저", "거", "이", "그", "좀", "때", "말",
    "안", "뭐", "왜", "이거", "그거", "저거", "진짜", "근데",
    "하다", "되다", "있다", "없다", "같다", "보다", "알다",
    "하는", "되는", "하고", "해서", "하면", "해도", "하는데",
    "은", "는", "이", "가", "을", "를", "에", "의", "도", "로",
    "다", "요", "네", "데", "지", "고", "서", "면", "게", "든",
    "들", "한", "할", "함", "해", "됨", "임", "음", "ㅋ", "ㅎ",
    "ㅠ", "ㅜ", "ㄷ", "ㅇ", "ㅈ", "ㄱ", "아", "오", "이제",
    "그냥", "너무", "되게", "많이", "약간", "일단", "아니",
    "네네", "ㅋㅋ", "ㅋㅋㅋ", "ㅎㅎ", "ㅎㅎㅎ", "ㅠㅠ",
}

# ── Kiwi 토크나이저 (싱글턴) ─────────────────────────────────────────

_kiwi: Kiwi | None = None


def _get_kiwi() -> Kiwi:
    global _kiwi
    if _kiwi is None:
        _kiwi = Kiwi()
    return _kiwi


def tokenize(text: str) -> list[str]:
    """명사(NNG, NNP) + 동사 어근(VV) + 형용사 어근(VA) 추출"""
    kiwi = _get_kiwi()
    tokens = []
    for token in kiwi.tokenize(text):
        if token.tag in ("NNG", "NNP", "VV", "VA") and len(token.form) > 1:
            if token.form not in STOPWORDS_KO:
                tokens.append(token.form)
    return tokens


def tokenize_batch(texts: list[str]) -> list[str]:
    """여러 메시지를 한번에 토큰화 (메시지 단위로 개별 처리)"""
    kiwi = _get_kiwi()
    all_tokens = []
    for text in texts:
        for token in kiwi.tokenize(str(text)):
            if token.tag in ("NNG", "NNP", "VV", "VA") and len(token.form) > 1:
                if token.form not in STOPWORDS_KO:
                    all_tokens.append(token.form)
    return all_tokens


# ── 캐시 유틸리티 ────────────────────────────────────────────────────

def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.pkl")


def _load_cache(key: str):
    path = _cache_path(key)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return None


def _save_cache(key: str, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(key), "wb") as f:
        pickle.dump(data, f)


# ── 공통: 유저별 토큰화 텍스트 준비 ──────────────────────────────────

MAX_MESSAGES_PER_USER = 5000  # 유저당 최대 메시지 수 (샘플링)


def _prepare_user_tokens(df_clean: pd.DataFrame) -> dict[str, list[str]]:
    """유저별 토큰 리스트 (캐시 사용, 유저당 최대 5000 메시지 샘플링)"""
    cached = _load_cache("user_tokens")
    if cached is not None:
        return cached

    print("[text_analysis] Tokenizing messages per user (sampled)...")
    user_tokens = {}
    groups = list(df_clean.groupby("user_hash"))

    for i, (user_hash, group) in enumerate(groups):
        # 유저당 최대 N개 메시지 샘플링
        if len(group) > MAX_MESSAGES_PER_USER:
            sample = group.sample(n=MAX_MESSAGES_PER_USER, random_state=42)
        else:
            sample = group
        messages = sample["content"].astype(str).tolist()
        user_tokens[user_hash] = tokenize_batch(messages)
        if (i + 1) % 10 == 0:
            print(f"[text_analysis]   {i + 1}/{len(groups)} users tokenized")

    _save_cache("user_tokens", user_tokens)
    print(f"[text_analysis] Tokenization complete: {len(user_tokens)} users")
    return user_tokens


# ── 1. WordCloud ─────────────────────────────────────────────────────

def generate_wordclouds(
    df_clean: pd.DataFrame,
    user_registry: dict,
) -> dict[str, str]:
    """유저별 워드클라우드 PNG 생성. {user_hash: image_path} 반환."""
    cached = _load_cache("wordcloud_paths")
    if cached is not None:
        # 파일 존재 확인
        if all(os.path.exists(p) for p in cached.values()):
            print(f"[text_analysis] WordCloud: loaded {len(cached)} cached images")
            return cached

    os.makedirs(WORDCLOUD_DIR, exist_ok=True)
    user_tokens = _prepare_user_tokens(df_clean)

    paths = {}
    for user_hash, tokens in user_tokens.items():
        if len(tokens) < 10:
            continue
        freq = defaultdict(int)
        for t in tokens:
            freq[t] += 1

        wc = WordCloud(
            font_path=FONT_PATH,
            width=800,
            height=400,
            background_color="#0d1117",
            colormap="Set2",
            max_words=100,
        )
        wc.generate_from_frequencies(freq)

        img_path = os.path.join(WORDCLOUD_DIR, f"{user_hash}.png")
        wc.to_file(img_path)
        paths[user_hash] = img_path

    _save_cache("wordcloud_paths", paths)
    print(f"[text_analysis] WordCloud: generated {len(paths)} images")
    return paths


# ── 2. TF-IDF ────────────────────────────────────────────────────────

def compute_tfidf(
    df_clean: pd.DataFrame,
    user_registry: dict,
    community_map: dict[str, int],
    top_n: int = 20,
) -> dict:
    """유저별/커뮤니티별 특징 단어 추출.
    반환: {"users": {hash: [(word, score), ...]}, "communities": {id: [...]}}
    """
    cached = _load_cache("tfidf")
    if cached is not None:
        print(f"[text_analysis] TF-IDF: loaded from cache")
        return cached

    user_tokens = _prepare_user_tokens(df_clean)

    # 유저별 문서 (토큰을 공백으로 결합)
    user_hashes = list(user_tokens.keys())
    corpus = [" ".join(tokens) for tokens in user_tokens.values()]

    vectorizer = TfidfVectorizer(
        analyzer="word",
        token_pattern=r"(?u)\b\w+\b",
        max_features=5000,
    )
    tfidf_matrix = vectorizer.fit_transform(corpus)
    feature_names = vectorizer.get_feature_names_out()

    # 유저별 Top-N
    user_tfidf = {}
    for i, user_hash in enumerate(user_hashes):
        row = tfidf_matrix[i].toarray().flatten()
        top_indices = row.argsort()[-top_n:][::-1]
        user_tfidf[user_hash] = [
            (feature_names[j], round(float(row[j]), 4))
            for j in top_indices if row[j] > 0
        ]

    # 커뮤니티별 문서 결합
    community_texts = defaultdict(list)
    for user_hash, tokens in user_tokens.items():
        comm_id = community_map.get(user_hash, -1)
        if comm_id >= 0:
            community_texts[comm_id].extend(tokens)

    comm_corpus_ids = sorted(community_texts.keys())
    comm_corpus = [" ".join(community_texts[c]) for c in comm_corpus_ids]

    if len(comm_corpus) > 1:
        comm_vectorizer = TfidfVectorizer(
            analyzer="word",
            token_pattern=r"(?u)\b\w+\b",
            max_features=5000,
        )
        comm_matrix = comm_vectorizer.fit_transform(comm_corpus)
        comm_features = comm_vectorizer.get_feature_names_out()

        community_tfidf = {}
        for i, comm_id in enumerate(comm_corpus_ids):
            row = comm_matrix[i].toarray().flatten()
            top_indices = row.argsort()[-top_n:][::-1]
            community_tfidf[comm_id] = [
                (comm_features[j], round(float(row[j]), 4))
                for j in top_indices if row[j] > 0
            ]
    else:
        community_tfidf = {}

    result = {"users": user_tfidf, "communities": community_tfidf}
    _save_cache("tfidf", result)
    print(f"[text_analysis] TF-IDF: computed for {len(user_tfidf)} users, {len(community_tfidf)} communities")
    return result


# ── 3. LDA 토픽 모델링 ──────────────────────────────────────────────

def run_topic_modeling(
    df_clean: pd.DataFrame,
    n_topics: int = 10,
) -> dict:
    """LDA 토픽 모델링 + 월별 토픽 분포.
    반환: {"topics": [{id, keywords: [(word, weight)]}], "monthly": [{month, distribution: [float]}]}
    """
    cached = _load_cache("topics")
    if cached is not None:
        print(f"[text_analysis] Topics: loaded from cache")
        return cached

    print("[text_analysis] Running LDA topic modeling...")

    # 월별로 문서를 구성
    df_work = df_clean.copy()
    df_work["month"] = pd.to_datetime(df_work["timestamp"], unit="ms").dt.strftime("%Y-%m")
    months = sorted(df_work["month"].unique())

    # 전체 코퍼스: 메시지 단위로 토큰화 (샘플링으로 속도 확보)
    sample_size = min(30000, len(df_work))
    df_sample = df_work.sample(n=sample_size, random_state=42)

    kiwi = _get_kiwi()

    def tokenize_for_lda(text: str) -> str:
        tokens = []
        for token in kiwi.tokenize(str(text)):
            if token.tag in ("NNG", "NNP") and len(token.form) > 1:
                if token.form not in STOPWORDS_KO:
                    tokens.append(token.form)
        return " ".join(tokens)

    print(f"[text_analysis]   Tokenizing {sample_size:,} messages for LDA...")
    tokenized = df_sample["content"].apply(tokenize_for_lda)

    vectorizer = CountVectorizer(
        analyzer="word",
        token_pattern=r"(?u)\b\w+\b",
        max_features=3000,
        min_df=5,
        max_df=0.7,
    )
    doc_term = vectorizer.fit_transform(tokenized)
    feature_names = vectorizer.get_feature_names_out()

    lda = LatentDirichletAllocation(
        n_components=n_topics,
        random_state=42,
        max_iter=20,
        learning_method="online",
    )
    lda.fit(doc_term)

    # 토픽 키워드
    topics = []
    for i, component in enumerate(lda.components_):
        top_indices = component.argsort()[-10:][::-1]
        keywords = [
            (feature_names[j], round(float(component[j] / component.sum()), 4))
            for j in top_indices
        ]
        topics.append({"id": i, "keywords": keywords})

    # 월별 토픽 분포
    monthly = []
    for month in months:
        month_msgs = df_work[df_work["month"] == month]["content"]
        if len(month_msgs) == 0:
            continue
        month_sample = month_msgs.sample(n=min(5000, len(month_msgs)), random_state=42)
        month_tokenized = month_sample.apply(tokenize_for_lda)
        month_dtm = vectorizer.transform(month_tokenized)
        topic_dist = lda.transform(month_dtm).mean(axis=0)
        monthly.append({
            "month": month,
            "distribution": [round(float(v), 4) for v in topic_dist],
        })

    result = {"topics": topics, "monthly": monthly}
    _save_cache("topics", result)
    print(f"[text_analysis] Topics: {n_topics} topics extracted, {len(monthly)} months")
    return result


# ── 4. 감성 분석 ─────────────────────────────────────────────────────

def _load_sentiment_dict() -> dict[str, float]:
    """KNU 감성사전 로드. 없으면 빈 딕셔너리 반환."""
    if os.path.exists(SENTIMENT_DICT_PATH):
        with open(SENTIMENT_DICT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    print(f"[text_analysis] Sentiment dict not found: {SENTIMENT_DICT_PATH}")
    return {}


def _score_sentiment(text: str, sentiment_dict: dict[str, float]) -> float | None:
    """메시지의 감성 점수 계산 (-1.0 ~ 1.0). 감성어 없으면 None."""
    kiwi = _get_kiwi()
    scores = []
    for token in kiwi.tokenize(str(text)):
        if token.form in sentiment_dict:
            scores.append(sentiment_dict[token.form])
    return float(np.mean(scores)) if scores else None


def analyze_sentiment(
    df_clean: pd.DataFrame,
    community_map: dict[str, int],
) -> dict:
    """감성 분석 실행.
    반환: {
        "users": {hash: {positive, negative, neutral, avg_score}},
        "communities": {id: {positive, negative, neutral, avg_score}},
        "monthly": [{month, avg_score, positive_ratio}]
    }
    """
    cached = _load_cache("sentiment")
    if cached is not None:
        print(f"[text_analysis] Sentiment: loaded from cache")
        return cached

    sentiment_dict = _load_sentiment_dict()
    if not sentiment_dict:
        print("[text_analysis] Sentiment: no dictionary available, skipping")
        return {"users": {}, "communities": {}, "monthly": []}

    print(f"[text_analysis] Sentiment analysis with {len(sentiment_dict)} words...")

    # 샘플링 (전체 분석은 너무 오래 걸릴 수 있음)
    sample_size = min(50000, len(df_clean))
    df_sample = df_clean.sample(n=sample_size, random_state=42).copy()

    # 감성 점수 계산
    df_sample["sentiment"] = df_sample["content"].apply(
        lambda x: _score_sentiment(str(x), sentiment_dict)
    )
    df_scored = df_sample.dropna(subset=["sentiment"])
    print(f"[text_analysis]   Scored {len(df_scored):,} / {sample_size:,} messages")

    def _aggregate(scores: pd.Series) -> dict:
        pos = (scores > 0).sum()
        neg = (scores < 0).sum()
        neu = (scores == 0).sum()
        total = len(scores)
        return {
            "positive": round(pos / total, 4) if total else 0,
            "negative": round(neg / total, 4) if total else 0,
            "neutral": round(neu / total, 4) if total else 0,
            "avg_score": round(float(scores.mean()), 4) if total else 0,
            "count": total,
        }

    # 유저별
    user_sentiment = {}
    for user_hash, group in df_scored.groupby("user_hash"):
        user_sentiment[user_hash] = _aggregate(group["sentiment"])

    # 커뮤니티별
    df_scored["community"] = df_scored["user_hash"].map(community_map)
    community_sentiment = {}
    for comm_id, group in df_scored.groupby("community"):
        if comm_id >= 0:
            community_sentiment[int(comm_id)] = _aggregate(group["sentiment"])

    # 월별
    df_scored["month"] = pd.to_datetime(df_scored["timestamp"], unit="ms").dt.strftime("%Y-%m")
    monthly_sentiment = []
    for month, group in sorted(df_scored.groupby("month")):
        agg = _aggregate(group["sentiment"])
        agg["month"] = month
        monthly_sentiment.append(agg)

    result = {
        "users": user_sentiment,
        "communities": community_sentiment,
        "monthly": monthly_sentiment,
    }
    _save_cache("sentiment", result)
    print(f"[text_analysis] Sentiment: {len(user_sentiment)} users, {len(community_sentiment)} communities")
    return result


# ── Gemini 감성 보정 ─────────────────────────────────────────────────

def calibrate_sentiment_with_gemini(
    df_clean: pd.DataFrame,
    community_map: dict[str, int],
    knu_sentiment: dict,
    samples_per_community: int = 30,
) -> dict | None:
    """Gemini로 KNU 감성 결과를 검증/보정. API 키 없으면 None."""
    if not GEMINI_API_KEY:
        return None

    import requests as req

    communities = set(community_map.values())
    calibration = {}

    for comm_id in sorted(communities):
        comm_users = [h for h, c in community_map.items() if c == comm_id]
        comm_msgs = df_clean[df_clean["user_hash"].isin(comm_users)]
        if len(comm_msgs) == 0:
            continue

        sample = comm_msgs.sample(n=min(samples_per_community, len(comm_msgs)), random_state=42)
        msg_list = "\n".join(f"- {row['content']}" for _, row in sample.iterrows())

        prompt = f"""다음은 카카오톡 채팅방의 커뮤니티 {comm_id} 메시지 샘플입니다.
각 메시지의 감성을 positive/negative/neutral로 분류하고, 전체적인 분위기를 요약해주세요.

[메시지 ({len(sample)}개)]
{msg_list}

JSON으로 응답:
{{"positive_ratio": 0.0~1.0, "negative_ratio": 0.0~1.0, "neutral_ratio": 0.0~1.0, "mood_summary": "한 줄 요약"}}"""

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
            resp = req.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500},
            })
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            import re
            clean = re.sub(r"^```[a-zA-Z]*\n", "", raw)
            clean = re.sub(r"```$", "", clean).strip()
            gemini_result = json.loads(clean)
            calibration[comm_id] = gemini_result
            print(f"[text_analysis] Gemini calibration for community {comm_id}: {gemini_result.get('mood_summary', '')}")
        except Exception as e:
            print(f"[text_analysis] Gemini calibration failed for community {comm_id}: {e}")

    if calibration:
        _save_cache("sentiment_gemini", calibration)

    return calibration


# ── 전체 텍스트 분석 파이프라인 ──────────────────────────────────────

class TextAnalysisResult:
    """텍스트 분석 결과 컨테이너"""

    def __init__(self):
        self.wordcloud_paths: dict[str, str] = {}
        self.tfidf: dict = {}
        self.topics: dict = {}
        self.sentiment: dict = {}
        self.gemini_calibration: dict | None = None


def run_text_analysis(
    df_clean: pd.DataFrame,
    user_registry: dict,
    community_map: dict[str, int],
) -> TextAnalysisResult:
    """전체 텍스트 분석 파이프라인"""
    result = TextAnalysisResult()

    result.wordcloud_paths = generate_wordclouds(df_clean, user_registry)
    result.tfidf = compute_tfidf(df_clean, user_registry, community_map)
    result.topics = run_topic_modeling(df_clean)
    result.sentiment = analyze_sentiment(df_clean, community_map)
    result.gemini_calibration = calibrate_sentiment_with_gemini(
        df_clean, community_map, result.sentiment
    )

    return result
