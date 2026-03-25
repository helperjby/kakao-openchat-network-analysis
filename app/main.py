"""
FastAPI 서버 — 네트워크 분석 + 텍스트 분석 + 유저 분류 API
"""

import time
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.analysis import run_analysis, NetworkAnalysisResult, build_user_registry
from app.nickname_mapper import load_or_generate_nickname_map, nickname_map_to_hash
from app.text_analysis import run_text_analysis, TextAnalysisResult
from app.user_classification import classify_users

app = FastAPI(title="Chat Network Analysis")

# ── 정적 파일 ──────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── 분석 결과 캐시 ─────────────────────────────────────────────────────

_result: NetworkAnalysisResult | None = None
_text_result: TextAnalysisResult | None = None
_user_types: dict | None = None
_df_clean = None  # 텍스트 분석용 DataFrame 보관


def _get_result() -> NetworkAnalysisResult:
    global _result
    if _result is None:
        raise HTTPException(status_code=503, detail="분석이 아직 완료되지 않았습니다.")
    return _result


def _get_text_result() -> TextAnalysisResult:
    global _text_result
    if _text_result is None:
        raise HTTPException(status_code=503, detail="텍스트 분석이 아직 완료되지 않았습니다.")
    return _text_result


def _get_user_types() -> dict:
    global _user_types
    if _user_types is None:
        raise HTTPException(status_code=503, detail="유저 분류가 아직 완료되지 않았습니다.")
    return _user_types


# ── 서버 시작 시 분석 실행 ─────────────────────────────────────────────

def _run_extended_analysis():
    """텍스트 분석 + 유저 분류 (백그라운드 스레드)"""
    global _text_result, _user_types, _df_clean
    t0 = time.time()

    if _result is None:
        print("[server] Extended analysis skipped: network analysis not ready")
        return

    try:
        from app.analysis import load_messages, filter_noise
        df = load_messages()
        df_clean = filter_noise(df)
        _df_clean = df_clean

        net = _result  # 타입 가드

        # 텍스트 분석
        print("[server] Starting text analysis...")
        _text_result = run_text_analysis(
            df_clean,
            net.user_registry,
            net.community_map,
        )
        print(f"[server] Text analysis complete in {time.time() - t0:.1f}s")

        # 유저 분류
        t1 = time.time()
        print("[server] Starting user classification...")
        _user_types = classify_users(
            df, df_clean,
            net.centrality,
            net.community_map,
            net.user_registry,
        )
        print(f"[server] User classification complete in {time.time() - t1:.1f}s")

    except Exception as e:
        print(f"[server] Extended analysis failed: {e}")
        import traceback
        traceback.print_exc()


@app.on_event("startup")
async def startup():
    global _result
    print("[server] Starting network analysis...")
    t0 = time.time()

    # 닉네임 매핑
    from app.analysis import load_messages
    df = load_messages()
    user_registry = build_user_registry(df)
    name_to_hash = {v: k for k, v in user_registry.items()}

    nickname_map = load_or_generate_nickname_map(user_registry)
    nick_to_hash = nickname_map_to_hash(nickname_map, name_to_hash)

    # 네트워크 분석 실행
    _result = run_analysis(nickname_to_hash=nick_to_hash)

    elapsed = time.time() - t0
    print(f"[server] Network analysis complete in {elapsed:.1f}s")
    print(f"[server] {_result.graph.number_of_nodes()} nodes, {_result.graph.number_of_edges()} edges, {len(_result.communities)} communities")

    # 텍스트 분석 + 유저 분류를 백그라운드에서 실행
    thread = threading.Thread(target=_run_extended_analysis, daemon=True)
    thread.start()
    print("[server] Extended analysis started in background thread")


# ── 기존 라우트 ───────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/network")
async def get_network():
    """전체 네트워크 그래프 JSON"""
    return _get_result().to_network_json()


@app.get("/api/users")
async def get_users(q: str = ""):
    """유저 목록 (검색 자동완성)"""
    result = _get_result()
    if q:
        return result.search_user(q)
    users = []
    for n in result.graph.nodes():
        users.append({
            "id": n,
            "label": result.graph.nodes[n]["label"],
            "msg_count": result.graph.nodes[n]["msg_count"],
        })
    return sorted(users, key=lambda x: x["msg_count"], reverse=True)


@app.get("/api/user/{user_id}")
async def get_user(user_id: str):
    """특정 유저의 ego 네트워크 + 상세 정보"""
    result = _get_result()

    if user_id not in result.graph:
        candidates = result.search_user(user_id)
        if not candidates:
            raise HTTPException(status_code=404, detail=f"유저 '{user_id}'를 찾을 수 없습니다.")
        user_id = candidates[0]["id"]

    ego = result.get_ego_network(user_id)
    if ego is None:
        raise HTTPException(status_code=404, detail=f"유저 '{user_id}'의 네트워크를 구성할 수 없습니다.")
    return ego


# ── 텍스트 분석 라우트 ────────────────────────────────────────────────

@app.get("/api/text/wordcloud/{user_id}")
async def get_wordcloud(user_id: str):
    """유저별 워드클라우드 이미지"""
    text_result = _get_text_result()
    result = _get_result()

    # user_id → hash 해석
    if user_id not in result.graph:
        candidates = result.search_user(user_id)
        if not candidates:
            raise HTTPException(status_code=404, detail=f"유저 '{user_id}'를 찾을 수 없습니다.")
        user_id = candidates[0]["id"]

    img_path = text_result.wordcloud_paths.get(user_id)
    if not img_path or not Path(img_path).exists():
        raise HTTPException(status_code=404, detail="워드클라우드가 생성되지 않았습니다.")

    return FileResponse(img_path, media_type="image/png")


@app.get("/api/text/tfidf")
async def get_tfidf(scope: str = "user", id: str = ""):
    """TF-IDF 특징 단어. scope=user|community, id=user_hash|community_id"""
    text_result = _get_text_result()
    result = _get_result()

    if scope == "community":
        if id:
            comm_data = text_result.tfidf.get("communities", {}).get(int(id))
            if comm_data is None:
                raise HTTPException(status_code=404, detail=f"커뮤니티 {id}를 찾을 수 없습니다.")
            return {"scope": "community", "id": int(id), "words": comm_data}
        return {"scope": "community", "data": text_result.tfidf.get("communities", {})}

    # user scope
    if id:
        if id not in result.graph:
            candidates = result.search_user(id)
            if not candidates:
                raise HTTPException(status_code=404, detail=f"유저 '{id}'를 찾을 수 없습니다.")
            id = candidates[0]["id"]
        user_data = text_result.tfidf.get("users", {}).get(id)
        if user_data is None:
            raise HTTPException(status_code=404, detail=f"유저 '{id}'의 TF-IDF 데이터를 찾을 수 없습니다.")
        return {"scope": "user", "id": id, "label": result.graph.nodes[id]["label"], "words": user_data}

    # 전체 유저 (단어 수만 요약)
    summary = []
    for user_hash, words in text_result.tfidf.get("users", {}).items():
        if user_hash in result.graph:
            summary.append({
                "id": user_hash,
                "label": result.graph.nodes[user_hash]["label"],
                "top_words": words[:5],
            })
    return {"scope": "user", "data": summary}


@app.get("/api/text/topics")
async def get_topics():
    """LDA 토픽 목록 + 월별 추이"""
    text_result = _get_text_result()
    return text_result.topics


@app.get("/api/text/sentiment")
async def get_sentiment(scope: str = "all"):
    """감성 분석 결과. scope=all|users|communities|monthly"""
    text_result = _get_text_result()
    s = text_result.sentiment

    if scope == "users":
        result = _get_result()
        users_with_labels = {}
        for user_hash, data in s.get("users", {}).items():
            if user_hash in result.graph:
                users_with_labels[user_hash] = {
                    **data,
                    "label": result.graph.nodes[user_hash]["label"],
                }
        return {"scope": "users", "data": users_with_labels}
    elif scope == "communities":
        return {"scope": "communities", "data": s.get("communities", {})}
    elif scope == "monthly":
        return {"scope": "monthly", "data": s.get("monthly", [])}

    # all
    response = {
        "users": s.get("users", {}),
        "communities": s.get("communities", {}),
        "monthly": s.get("monthly", []),
    }
    if text_result.gemini_calibration:
        response["gemini_calibration"] = text_result.gemini_calibration
    return response


# ── 유저 분류 라우트 ─────────────────────────────────────────────────

@app.get("/api/user-types")
async def get_user_types():
    """유저 유형 분류 결과"""
    return _get_user_types()


@app.get("/api/analysis-status")
async def get_analysis_status():
    """분석 진행 상태"""
    return {
        "network": _result is not None,
        "text": _text_result is not None,
        "user_types": _user_types is not None,
    }
