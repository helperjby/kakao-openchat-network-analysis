"""
FastAPI 서버 — 네트워크 분석 API + 정적 파일 서빙
"""

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.analysis import run_analysis, NetworkAnalysisResult
from app.nickname_mapper import load_or_generate_nickname_map, nickname_map_to_hash

app = FastAPI(title="Chat Network Analysis")

# ── 정적 파일 ──────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── 분석 결과 캐시 ─────────────────────────────────────────────────────

_result: NetworkAnalysisResult | None = None


def _get_result() -> NetworkAnalysisResult:
    global _result
    if _result is None:
        raise HTTPException(status_code=503, detail="분석이 아직 완료되지 않았습니다.")
    return _result


# ── 서버 시작 시 분석 실행 ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global _result
    print("[server] Starting network analysis...")
    t0 = time.time()

    # 닉네임 매핑
    from app.analysis import load_messages, build_user_registry
    df = load_messages()
    user_registry = build_user_registry(df)
    name_to_hash = {v: k for k, v in user_registry.items()}

    nickname_map = load_or_generate_nickname_map(user_registry)
    nick_to_hash = nickname_map_to_hash(nickname_map, name_to_hash)

    # 분석 실행
    _result = run_analysis(nickname_to_hash=nick_to_hash)

    elapsed = time.time() - t0
    print(f"[server] Analysis complete in {elapsed:.1f}s")
    print(f"[server] {_result.graph.number_of_nodes()} nodes, {_result.graph.number_of_edges()} edges, {len(_result.communities)} communities")


# ── 라우트 ─────────────────────────────────────────────────────────────

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
    # 전체 유저 목록 (메시지 수 내림차순)
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

    # user_id가 hash가 아닌 이름일 수 있음
    if user_id not in result.graph:
        candidates = result.search_user(user_id)
        if not candidates:
            raise HTTPException(status_code=404, detail=f"유저 '{user_id}'를 찾을 수 없습니다.")
        user_id = candidates[0]["id"]

    ego = result.get_ego_network(user_id)
    if ego is None:
        raise HTTPException(status_code=404, detail=f"유저 '{user_id}'의 네트워크를 구성할 수 없습니다.")
    return ego
