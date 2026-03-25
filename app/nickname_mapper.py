"""
LLM 기반 비공식 닉네임 → 실제 유저 매핑
Gemini API를 사용하여 채팅 메시지에서 사용되는 별명을 실제 닉네임에 매핑한다.
결과는 JSON 파일로 캐싱. CSV로 내보내 수동 편집 가능.
"""

import csv
import json
import os
import re
import sqlite3

import requests
import pandas as pd

from app.config import (
    DB_PATH, CHANNEL_ID, GEMINI_API_KEY, GEMINI_MODEL, NICKNAME_CACHE_PATH,
    ANALYSIS_START_MS, ANALYSIS_END_MS, NICKNAME_REVIEW_PATH,
)


def _call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "topK": 40,
            "topP": 0.9,
            "maxOutputTokens": 2000,
        },
    }

    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()

    try:
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini 응답 파싱 실패: {data}")

    if "usageMetadata" in data:
        u = data["usageMetadata"]
        print(f"[nickname_mapper] Tokens - in: {u.get('promptTokenCount', 0)}, out: {u.get('candidatesTokenCount', 0)}")

    # 마크다운 코드블록 제거
    clean = re.sub(r"^```[a-zA-Z]*\n", "", raw)
    clean = re.sub(r"```$", "", clean).strip()
    return clean


def _sample_messages(n: int = 150) -> list[str]:
    """닉네임이 포함될 가능성이 높은 메시지 샘플링"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT content FROM chat_logs
        WHERE channel_id = ?
          AND user_hash IS NOT NULL
          AND length(content) > 5
          AND content NOT LIKE '%을 보냈습니다%'
          AND content NOT LIKE 'http%'
          AND timestamp >= ? AND timestamp < ?
        ORDER BY RANDOM()
        LIMIT ?
        """,
        conn,
        params=(CHANNEL_ID, ANALYSIS_START_MS, ANALYSIS_END_MS, n),
    )
    conn.close()
    return df["content"].tolist()


def _get_user_names() -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT user_name, COUNT(*) as cnt
        FROM chat_logs
        WHERE channel_id = ? AND user_name IS NOT NULL
          AND timestamp >= ? AND timestamp < ?
        GROUP BY user_hash
        ORDER BY cnt DESC
        """,
        conn,
        params=(CHANNEL_ID, ANALYSIS_START_MS, ANALYSIS_END_MS),
    )
    conn.close()
    return df["user_name"].tolist()


def generate_nickname_map() -> dict[str, str]:
    """Gemini에게 닉네임 매핑을 요청하고 결과를 반환"""
    user_names = _get_user_names()
    sample_msgs = _sample_messages(150)

    name_list = "\n".join(f"- {n}" for n in user_names)
    msg_list = "\n".join(sample_msgs[:150])

    prompt = f"""다음은 카카오톡 그룹채팅의 참가자 목록과 메시지 샘플입니다.

[참가자 목록 ({len(user_names)}명)]
{name_list}

[메시지 샘플 ({len(sample_msgs)}개)]
{msg_list}

위 메시지에서 사용된 비공식 닉네임/별명/줄임말이 참가자 목록의 누구를 지칭하는지 매핑해주세요.

규칙:
1. 확실한 매핑만 포함하세요. 불확실하면 제외.
2. 참가자 이름 자체는 제외하세요 (예: "실바" → "실바"는 불필요).
3. 부분 일치나 변형만 포함하세요 (예: "실노인" → "실바").

순수 JSON만 출력하세요. 설명 없이:
{{"별명1": "실제닉네임1", "별명2": "실제닉네임2"}}"""

    print("[nickname_mapper] Calling Gemini for nickname mapping...")
    raw = _call_gemini(prompt)

    # JSON 파싱
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            print(f"[nickname_mapper] Failed to parse response: {raw[:200]}")
            result = {}

    print(f"[nickname_mapper] Mapped {len(result)} nicknames: {result}")
    return result


def _find_sample_messages_for_nick(nick: str, n: int = 3) -> list[str]:
    """특정 닉네임이 포함된 메시지 예시를 찾는다."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT content FROM chat_logs
        WHERE channel_id = ? AND content LIKE ?
          AND timestamp >= ? AND timestamp < ?
        ORDER BY RANDOM()
        LIMIT ?
        """,
        conn,
        params=(CHANNEL_ID, f"%{nick}%", ANALYSIS_START_MS, ANALYSIS_END_MS, n),
    )
    conn.close()
    return df["content"].tolist()


def export_review_csv(nickname_map: dict[str, str], user_registry: dict) -> str:
    """닉네임 매핑을 편집 가능한 CSV로 내보낸다."""
    name_to_hash = {v: k for k, v in user_registry.items()}

    # 유저별 메시지 수 조회
    conn = sqlite3.connect(DB_PATH)
    msg_counts = pd.read_sql_query(
        """
        SELECT user_hash, COUNT(*) as cnt FROM chat_logs
        WHERE channel_id = ? AND timestamp >= ? AND timestamp < ?
        GROUP BY user_hash
        """,
        conn,
        params=(CHANNEL_ID, ANALYSIS_START_MS, ANALYSIS_END_MS),
    ).set_index("user_hash")["cnt"].to_dict()
    conn.close()

    os.makedirs(os.path.dirname(NICKNAME_REVIEW_PATH), exist_ok=True)

    with open(NICKNAME_REVIEW_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["nickname", "mapped_to", "user_hash", "msg_count", "sample_messages", "approved"])

        for nick, real_name in sorted(nickname_map.items()):
            user_hash = name_to_hash.get(real_name, "")
            if not user_hash:
                for name, h in name_to_hash.items():
                    if real_name in name or name in real_name:
                        user_hash = h
                        break
            msg_count = msg_counts.get(user_hash, 0)
            samples = _find_sample_messages_for_nick(nick, 3)
            sample_str = " | ".join(s.replace("\n", " ")[:80] for s in samples)

            writer.writerow([nick, real_name, user_hash, msg_count, sample_str, "TRUE"])

    print(f"[nickname_mapper] Exported review CSV ({len(nickname_map)} entries) → {NICKNAME_REVIEW_PATH}")
    return NICKNAME_REVIEW_PATH


def load_nickname_map_from_csv() -> dict[str, str] | None:
    """CSV에서 approved=TRUE인 행만 로드. 파일 없으면 None 반환."""
    if not os.path.exists(NICKNAME_REVIEW_PATH):
        return None

    result = {}
    with open(NICKNAME_REVIEW_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("approved", "").strip().upper() == "TRUE":
                result[row["nickname"]] = row["mapped_to"]

    print(f"[nickname_mapper] Loaded from review CSV ({len(result)} approved entries)")
    return result


def load_or_generate_nickname_map(user_registry: dict) -> dict[str, str]:
    """우선순위: CSV → JSON → Gemini 생성"""
    # 1. CSV (사용자 편집본) 우선
    csv_map = load_nickname_map_from_csv()
    if csv_map is not None:
        return csv_map

    # 2. JSON 캐시
    if os.path.exists(NICKNAME_CACHE_PATH):
        with open(NICKNAME_CACHE_PATH, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(f"[nickname_mapper] Loaded cached map ({len(cached)} entries)")
        # JSON이 있으면 CSV도 생성해둔다
        export_review_csv(cached, user_registry)
        return cached

    # 3. API 키가 없으면 빈 매핑 반환
    if not GEMINI_API_KEY:
        print("[nickname_mapper] No GEMINI_API_KEY, skipping nickname mapping")
        return {}

    # 4. Gemini 생성
    nickname_map = generate_nickname_map()

    # JSON + CSV 동시 저장
    os.makedirs(os.path.dirname(NICKNAME_CACHE_PATH), exist_ok=True)
    with open(NICKNAME_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(nickname_map, f, ensure_ascii=False, indent=2)
    print(f"[nickname_mapper] Saved to {NICKNAME_CACHE_PATH}")

    export_review_csv(nickname_map, user_registry)

    return nickname_map


def nickname_map_to_hash(nickname_map: dict[str, str], name_to_hash: dict[str, str]) -> dict[str, str]:
    """별명 → 닉네임 매핑을 별명 → user_hash 매핑으로 변환"""
    result = {}
    for nick, real_name in nickname_map.items():
        if real_name in name_to_hash:
            result[nick] = name_to_hash[real_name]
        else:
            # 부분 매치 시도
            for name, h in name_to_hash.items():
                if real_name in name or name in real_name:
                    result[nick] = h
                    break
    return result
