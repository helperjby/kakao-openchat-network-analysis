"""
채팅 네트워크 분석 엔진
- 데이터 로드 & 전처리
- 상호작용 추론 (시간 근접성 + @멘션 + 닉네임 매핑)
- NetworkX 그래프 구성
- 중심성 분석 & 커뮤니티 탐지
"""

import re
import sqlite3
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import networkx as nx
from networkx.algorithms.community import louvain_communities, modularity

from app.config import (
    DB_PATH, CHANNEL_ID, TIME_WINDOW_MS,
    WEIGHT_TEMPORAL, WEIGHT_MENTION, WEIGHT_NICKNAME,
    NICKNAME_CACHE_PATH, ANALYSIS_START_MS, ANALYSIS_END_MS,
)

# ── 노이즈 필터링 패턴 (MiruBot stats_service.py L11-19) ──────────────

_EMOTICON_RE = re.compile(
    r"^(이모티콘|사진|동영상|샵검색)(을 보냈습니다\.?|( \d+장을 보냈습니다\.?))$"
)
_URL_RE = re.compile(r"https?://\S+")
_NOISE_RE = re.compile(r"^[ㄱ-ㅎㅋㅎㅉㅠㅜㅡ\s.!?~ㅇㅎ]+$")
_MENTION_RE = re.compile(r"@(\S+)")


def _is_noise(content: str) -> bool:
    content = content.strip()
    if not content or len(content) < 2:
        return True
    if _EMOTICON_RE.match(content):
        return True
    if _URL_RE.match(content):
        return True
    if _NOISE_RE.match(content):
        return True
    return False


# ── 데이터 로드 ────────────────────────────────────────────────────────

def load_messages() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT id, user_hash, user_name, content, timestamp
        FROM chat_logs
        WHERE channel_id = ? AND user_hash IS NOT NULL AND user_name IS NOT NULL
          AND timestamp >= ? AND timestamp < ?
        ORDER BY timestamp
        """,
        conn,
        params=(CHANNEL_ID, ANALYSIS_START_MS, ANALYSIS_END_MS),
    )
    conn.close()
    print(f"[analysis] Loaded {len(df):,} messages from {df['user_hash'].nunique()} users")
    return df


# ── 유저 레지스트리 ────────────────────────────────────────────────────

def build_user_registry(df: pd.DataFrame) -> dict:
    """user_hash → 최신 user_name 매핑"""
    return (
        df.sort_values("timestamp")
        .groupby("user_hash")["user_name"]
        .last()
        .to_dict()
    )


# ── 전처리 ─────────────────────────────────────────────────────────────

def filter_noise(df: pd.DataFrame) -> pd.DataFrame:
    mask = df["content"].apply(_is_noise)
    clean = df[~mask].copy()
    print(f"[analysis] After noise filtering: {len(clean):,} / {len(df):,} ({len(clean)/len(df)*100:.1f}%)")
    return clean


# ── @멘션 추출 ─────────────────────────────────────────────────────────

def extract_mentions(content: str, name_to_hash: dict) -> list[str]:
    matches = _MENTION_RE.findall(content)
    resolved = []
    for m in matches:
        m = m.strip()
        if m in name_to_hash:
            resolved.append(name_to_hash[m])
        else:
            for name, h in name_to_hash.items():
                if m in name or name in m:
                    resolved.append(h)
                    break
    return resolved


# ── 엣지 구성 ──────────────────────────────────────────────────────────

def build_edges(
    df_clean: pd.DataFrame,
    name_to_hash: dict,
    nickname_to_hash: dict | None = None,
) -> dict[tuple, float]:
    """세 가지 신호를 결합하여 (hash_a, hash_b) → weight 딕셔너리 반환"""
    edges: dict[tuple, float] = defaultdict(float)

    timestamps = df_clean["timestamp"].values
    user_hashes = df_clean["user_hash"].values
    contents = df_clean["content"].values

    # 1) 시간 근접성
    for i in range(1, len(timestamps)):
        if timestamps[i] - timestamps[i - 1] > TIME_WINDOW_MS:
            continue
        a, b = user_hashes[i], user_hashes[i - 1]
        if a != b:
            edge = tuple(sorted([a, b]))
            edges[edge] += WEIGHT_TEMPORAL

    # 2) @멘션
    for i in range(len(contents)):
        sender = user_hashes[i]
        for target in extract_mentions(str(contents[i]), name_to_hash):
            if sender != target:
                edge = tuple(sorted([sender, target]))
                edges[edge] += WEIGHT_MENTION

    # 3) LLM 닉네임 매핑
    if nickname_to_hash:
        for i in range(len(contents)):
            content = str(contents[i])
            sender = user_hashes[i]
            for nick, target_hash in nickname_to_hash.items():
                if nick in content and sender != target_hash:
                    edge = tuple(sorted([sender, target_hash]))
                    edges[edge] += WEIGHT_NICKNAME

    print(f"[analysis] Edges: {len(edges)}, total weight: {sum(edges.values()):.0f}")
    return dict(edges)


# ── 그래프 구성 ────────────────────────────────────────────────────────

def build_graph(
    user_registry: dict,
    edges: dict[tuple, float],
    df: pd.DataFrame,
) -> nx.Graph:
    G = nx.Graph()

    msg_counts = df.groupby("user_hash").size().to_dict()

    for h, name in user_registry.items():
        G.add_node(h, label=name, msg_count=msg_counts.get(h, 0))

    for (a, b), w in edges.items():
        if a in G and b in G:
            G.add_edge(a, b, weight=w)

    isolates = list(nx.isolates(G))
    G.remove_nodes_from(isolates)
    print(f"[analysis] Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges (removed {len(isolates)} isolates)")
    return G


# ── 중심성 분석 ────────────────────────────────────────────────────────

def compute_centrality(G: nx.Graph) -> dict[str, dict]:
    degree = nx.degree_centrality(G)
    betweenness = nx.betweenness_centrality(G, weight="weight")
    pagerank = nx.pagerank(G, weight="weight")
    try:
        eigenvector = nx.eigenvector_centrality(G, weight="weight", max_iter=1000)
    except nx.PowerIterationFailedConvergence:
        eigenvector = {n: 0.0 for n in G.nodes()}

    result = {}
    for n in G.nodes():
        result[n] = {
            "degree": round(degree[n], 4),
            "betweenness": round(betweenness[n], 4),
            "pagerank": round(pagerank[n], 4),
            "eigenvector": round(eigenvector[n], 4),
        }
    return result


# ── 커뮤니티 탐지 ──────────────────────────────────────────────────────

def detect_communities(G: nx.Graph) -> tuple[list[set], dict[str, int], float]:
    communities = louvain_communities(G, weight="weight", resolution=1.0, seed=42)
    community_map = {}
    for i, comm in enumerate(communities):
        for node in comm:
            community_map[node] = i

    mod = modularity(G, communities, weight="weight")
    print(f"[analysis] Communities: {len(communities)}, modularity: {mod:.4f}")
    return communities, community_map, mod


# ── 전체 분석 파이프라인 ───────────────────────────────────────────────

class NetworkAnalysisResult:
    """분석 결과를 보관하는 컨테이너"""

    def __init__(self):
        self.graph: nx.Graph | None = None
        self.user_registry: dict = {}
        self.centrality: dict = {}
        self.communities: list[set] = []
        self.community_map: dict[str, int] = {}
        self.modularity: float = 0.0
        self.edges_raw: dict[tuple, float] = {}

    def to_network_json(self) -> dict:
        """전체 네트워크 JSON (프론트엔드용)"""
        G = self.graph
        nodes = []
        for n in G.nodes():
            nodes.append({
                "id": n,
                "label": G.nodes[n]["label"],
                "msg_count": G.nodes[n]["msg_count"],
                "community": self.community_map.get(n, -1),
                "centrality": self.centrality.get(n, {}),
            })

        edges = []
        for u, v, d in G.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "weight": round(d["weight"], 2),
            })

        community_list = []
        for i, comm in enumerate(self.communities):
            community_list.append({
                "id": i,
                "members": [
                    {"id": n, "label": G.nodes[n]["label"]}
                    for n in comm if n in G
                ],
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "communities": community_list,
            "stats": {
                "modularity": round(self.modularity, 4),
                "total_nodes": G.number_of_nodes(),
                "total_edges": G.number_of_edges(),
                "total_communities": len(self.communities),
            },
        }

    def get_ego_network(self, user_hash: str) -> dict | None:
        """특정 유저 중심 서브그래프 JSON"""
        G = self.graph
        if user_hash not in G:
            return None

        neighbors = list(G.neighbors(user_hash))
        sub_nodes = [user_hash] + neighbors
        subG = G.subgraph(sub_nodes)

        # 가장 많이 대화한 상대 정렬
        top_partners = sorted(
            [(nb, G[user_hash][nb]["weight"]) for nb in neighbors],
            key=lambda x: x[1],
            reverse=True,
        )

        # 중심성 순위 계산
        centrality_ranks = {}
        for metric in ["degree", "betweenness", "pagerank", "eigenvector"]:
            sorted_nodes = sorted(
                self.centrality.items(),
                key=lambda x: x[1].get(metric, 0),
                reverse=True,
            )
            for rank, (n, _) in enumerate(sorted_nodes, 1):
                if n == user_hash:
                    centrality_ranks[metric] = rank
                    break

        nodes = []
        for n in subG.nodes():
            nodes.append({
                "id": n,
                "label": G.nodes[n]["label"],
                "msg_count": G.nodes[n]["msg_count"],
                "community": self.community_map.get(n, -1),
                "centrality": self.centrality.get(n, {}),
                "is_center": n == user_hash,
            })

        edges = []
        for u, v, d in subG.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "weight": round(d["weight"], 2),
            })

        community_id = self.community_map.get(user_hash, -1)
        community_members = []
        if community_id >= 0 and community_id < len(self.communities):
            community_members = [
                {"id": n, "label": G.nodes[n]["label"]}
                for n in self.communities[community_id] if n in G
            ]

        return {
            "user": {
                "id": user_hash,
                "label": G.nodes[user_hash]["label"],
                "msg_count": G.nodes[user_hash]["msg_count"],
                "centrality": self.centrality.get(user_hash, {}),
                "centrality_ranks": centrality_ranks,
                "community": community_id,
            },
            "nodes": nodes,
            "edges": edges,
            "top_partners": [
                {"id": h, "label": G.nodes[h]["label"], "weight": round(w, 2)}
                for h, w in top_partners[:10]
            ],
            "community_members": community_members,
        }

    def search_user(self, query: str) -> list[dict]:
        """유저 검색 (이름 부분 매치)"""
        query_lower = query.lower()
        results = []
        for h, name in self.user_registry.items():
            if h not in self.graph:
                continue
            if query_lower in name.lower() or query_lower in h.lower():
                results.append({
                    "id": h,
                    "label": name,
                    "msg_count": self.graph.nodes[h]["msg_count"],
                })
        return sorted(results, key=lambda x: x["msg_count"], reverse=True)


def run_analysis(nickname_to_hash: dict | None = None) -> NetworkAnalysisResult:
    """전체 분석 파이프라인 실행"""
    result = NetworkAnalysisResult()

    # 1. 데이터 로드
    df = load_messages()
    result.user_registry = build_user_registry(df)
    name_to_hash = {v: k for k, v in result.user_registry.items()}

    # 2. 전처리
    df_clean = filter_noise(df)

    # 3. 엣지 구성
    result.edges_raw = build_edges(df_clean, name_to_hash, nickname_to_hash)

    # 4. 그래프 구성
    result.graph = build_graph(result.user_registry, result.edges_raw, df)

    # 5. 중심성 분석
    result.centrality = compute_centrality(result.graph)

    # 6. 커뮤니티 탐지
    result.communities, result.community_map, result.modularity = detect_communities(result.graph)

    return result
