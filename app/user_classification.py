"""
유저 유형 분류 모듈
- 네트워크/활동량/시간/메시지/소셜 피처 추출
- K-Means 클러스터링 + 자동 라벨링
"""

import os
import pickle
import re
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from app.config import CACHE_DIR

KST = timezone(timedelta(hours=9))

_MENTION_RE = re.compile(r"@(\S+)")


def extract_user_features(
    df: pd.DataFrame,
    df_clean: pd.DataFrame,
    centrality: dict[str, dict],
    community_map: dict[str, int],
) -> pd.DataFrame:
    """유저별 피처 매트릭스 생성"""
    users = list(centrality.keys())

    # 타임스탬프를 KST datetime으로
    df_work = df[df["user_hash"].isin(users)].copy()
    df_work["dt"] = pd.to_datetime(df_work["timestamp"], unit="ms", utc=True).dt.tz_convert(KST)
    df_work["hour"] = df_work["dt"].dt.hour
    df_work["weekday"] = df_work["dt"].dt.weekday  # 0=Mon, 6=Sun
    df_work["date"] = df_work["dt"].dt.date

    features = []
    for user_hash in users:
        user_df = df_work[df_work["user_hash"] == user_hash]
        user_clean = df_clean[df_clean["user_hash"] == user_hash]

        # 활동량
        msg_count = len(user_df)
        active_days = user_df["date"].nunique()
        msgs_per_day = msg_count / max(active_days, 1)

        # 시간 패턴
        hour_counts = user_df["hour"].value_counts()
        peak_hour = hour_counts.idxmax() if len(hour_counts) > 0 else 12
        night_msgs = user_df[(user_df["hour"] >= 22) | (user_df["hour"] < 6)]
        night_ratio = len(night_msgs) / max(msg_count, 1)
        weekend_msgs = user_df[user_df["weekday"] >= 5]
        weekend_ratio = len(weekend_msgs) / max(msg_count, 1)

        # 메시지 특성
        msg_lengths = user_clean["content"].astype(str).str.len()
        avg_length = msg_lengths.mean() if len(msg_lengths) > 0 else 0
        # 어휘 다양성: 고유 단어 / 전체 단어
        all_words = " ".join(user_clean["content"].astype(str)).split()
        vocab_richness = len(set(all_words)) / max(len(all_words), 1)

        # 소셜: 멘션 사용률
        mention_count = user_clean["content"].astype(str).apply(
            lambda x: len(_MENTION_RE.findall(x))
        ).sum()
        mention_rate = mention_count / max(len(user_clean), 1)

        # 네트워크 중심성
        c = centrality.get(user_hash, {})

        features.append({
            "user_hash": user_hash,
            "msg_count": msg_count,
            "active_days": active_days,
            "msgs_per_day": msgs_per_day,
            "peak_hour": peak_hour,
            "night_ratio": night_ratio,
            "weekend_ratio": weekend_ratio,
            "avg_length": avg_length,
            "vocab_richness": vocab_richness,
            "mention_rate": mention_rate,
            "degree": c.get("degree", 0),
            "betweenness": c.get("betweenness", 0),
            "pagerank": c.get("pagerank", 0),
            "eigenvector": c.get("eigenvector", 0),
        })

    return pd.DataFrame(features).set_index("user_hash")


def _assign_labels(centers: np.ndarray, feature_names: list[str]) -> list[str]:
    """클러스터 중심점 특성에 따라 한국어 라벨 부여"""
    labels = []
    for center in centers:
        feature_scores = dict(zip(feature_names, center))

        # 규칙 기반 라벨링 (정규화된 값 기준, 0 = 평균)
        if feature_scores["degree"] > 0.8 and feature_scores["msg_count"] > 0.5:
            labels.append("허브형 (Hub)")
        elif feature_scores["night_ratio"] > 0.8 and feature_scores["msg_count"] > 0.3:
            labels.append("야행성 다작러 (Night Owl)")
        elif feature_scores["msg_count"] < -0.5 and feature_scores["degree"] < -0.3:
            labels.append("조용한 관찰자 (Observer)")
        elif feature_scores["mention_rate"] > 0.5 and feature_scores["degree"] > 0.3:
            labels.append("소통러 (Connector)")
        elif feature_scores["avg_length"] > 0.7 and feature_scores["vocab_richness"] > 0.5:
            labels.append("에세이스트 (Essayist)")
        elif feature_scores["msgs_per_day"] > 0.7:
            labels.append("활발한 참여자 (Active)")
        elif feature_scores["weekend_ratio"] > 0.7:
            labels.append("주말형 (Weekender)")
        else:
            # 가장 높은 특성으로 라벨링
            top_feat = max(feature_scores, key=feature_scores.get)
            label_map = {
                "msg_count": "다작러", "active_days": "꾸준한 참여자",
                "msgs_per_day": "집중형", "night_ratio": "야행성",
                "weekend_ratio": "주말형", "avg_length": "장문형",
                "vocab_richness": "다양한 어휘", "mention_rate": "소통형",
                "degree": "연결형", "betweenness": "중개자",
                "pagerank": "영향력자", "eigenvector": "핵심 멤버",
                "peak_hour": "일반형",
            }
            labels.append(label_map.get(top_feat, "일반형"))

    return labels


def classify_users(
    df: pd.DataFrame,
    df_clean: pd.DataFrame,
    centrality: dict[str, dict],
    community_map: dict[str, int],
    user_registry: dict,
) -> dict:
    """유저 유형 분류 실행.
    반환: {
        "users": {hash: {type, cluster_id, features: {}}},
        "clusters": [{id, label, size, center: {}}],
        "feature_names": [str]
    }
    """
    cache_path = os.path.join(CACHE_DIR, "user_types.pkl")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            cached = pickle.load(f)
        print(f"[user_classification] Loaded from cache")
        return cached

    print("[user_classification] Extracting user features...")
    feat_df = extract_user_features(df, df_clean, centrality, community_map)
    feature_names = list(feat_df.columns)

    # 정규화
    scaler = StandardScaler()
    X = scaler.fit_transform(feat_df.values)

    # 최적 k 탐색 (3~7)
    best_k, best_score = 3, -1
    for k in range(3, min(8, len(feat_df))):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        score = silhouette_score(X, labels)
        print(f"[user_classification]   k={k}, silhouette={score:.4f}")
        if score > best_score:
            best_k, best_score = k, score

    print(f"[user_classification] Best k={best_k} (silhouette={best_score:.4f})")
    km = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    cluster_labels = km.fit_predict(X)

    # 클러스터 라벨 부여
    type_labels = _assign_labels(km.cluster_centers_, feature_names)

    # 결과 구성
    users_result = {}
    for i, user_hash in enumerate(feat_df.index):
        cluster_id = int(cluster_labels[i])
        users_result[user_hash] = {
            "label": user_registry.get(user_hash, user_hash),
            "type": type_labels[cluster_id],
            "cluster_id": cluster_id,
            "features": {k: round(float(v), 4) for k, v in feat_df.loc[user_hash].items()},
        }

    clusters = []
    for cid in range(best_k):
        mask = cluster_labels == cid
        center = {
            feature_names[j]: round(float(km.cluster_centers_[cid][j]), 4)
            for j in range(len(feature_names))
        }
        clusters.append({
            "id": cid,
            "label": type_labels[cid],
            "size": int(mask.sum()),
            "center": center,
        })

    result = {
        "users": users_result,
        "clusters": clusters,
        "feature_names": feature_names,
    }

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(result, f)
    print(f"[user_classification] Classified {len(users_result)} users into {best_k} types")

    return result
