# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

카카오톡 오픈채팅(수다방) 소셜 네트워크 분석 웹앱. 2025년 데이터 기준 124만 메시지 / 46명 유저.
FastAPI 백엔드 + D3.js & Chart.js 프론트엔드. 네트워크 분석 + 텍스트 분석 + 유저 유형 분류.

## Commands

```bash
# 서버 실행
python -m uvicorn app.main:app --reload --port 8001

# 브라우저 접속
http://localhost:8001

# DB 갱신 (라즈베리파이에서)
scp jby@192.168.0.133:/home/jby/MiruBot/server/data/chat.db* data/

# 캐시 초기화 (데이터 변경 후)
rm -rf data/cache/
```

## Architecture

```
chat.db -> analysis.py (전처리 + NetworkX 그래프 + 중심성 + 커뮤니티)
                |
         text_analysis.py (kiwipiepy 토큰화 + WordCloud + TF-IDF + LDA + 감성)
         user_classification.py (피처 추출 + K-Means 클러스터링)
                |
         main.py (FastAPI 12개 라우트, startup 시 분석 + 백그라운드 텍스트/분류)
                |
         static/ (D3.js 네트워크 + Chart.js 차트, 3탭 대시보드)
```

### 핵심 데이터 흐름

- **startup**: `load_messages()` (2025 필터) -> `build_user_registry()` -> `load_or_generate_nickname_map()` -> `run_analysis()` -> 메모리 캐시
- **백그라운드 스레드**: `run_text_analysis()` + `classify_users()` -> pickle 캐시
- **API**: `/api/network`, `/api/user/{id}`, `/api/text/*`, `/api/user-types`, `/api/analysis-status`
- **프론트엔드**: 상태 폴링 (5초) -> 분석 완료 시 자동 초기화

### 상호작용 추론 (3가지 신호, 가산 가중치)

1. 시간 근접성 (3분 이내 연속 메시지) - weight 1.0
2. @멘션 (명시적 언급) - weight 3.0
3. LLM 닉네임 매핑 (Gemini API, 선택적) - weight 2.0

### 주요 설계 결정

- **분석 1회 캐싱**: 124만 행 처리에 ~16초. startup에서 1회 실행 후 메모리 캐시.
- **텍스트 분석 백그라운드**: 네트워크 분석 후 별도 스레드에서 실행. API는 503 반환 후 완료 시 200.
- **Gemini 없이도 동작**: `GEMINI_API_KEY` 미설정 시 닉네임 매핑/감성 보정 스킵.
- **닉네임 매핑 우선순위**: CSV (사용자 편집) > JSON 캐시 > Gemini 생성.
- **토큰화 샘플링**: 유저당 최대 5000 메시지 (전체 처리 시 44분 -> 샘플링 시 ~2분).
- **노이즈 필터링**: 이모티콘, URL, 자모만, 짧은 메시지. 75.4% 통과.

## Data

- `data/chat.db` (313MB) - `.gitignore` 포함, 별도 scp 필요
- `data/nickname_map.json` - Gemini 매핑 캐시 (자동 생성)
- `data/nickname_map_review.csv` - 편집 가능한 매핑 (Excel로 열기)
- `data/knu_sentiment.json` - 한국어 감성사전 208단어
- `data/cache/` - pickle 캐시 + 워드클라우드 PNG
- `.env` - `GEMINI_API_KEY` (gitignore 포함)
- 채널 ID: `18301468764762222`

## Key Classes

- `NetworkAnalysisResult` (`analysis.py`): 그래프, 중심성, 커뮤니티 컨테이너
- `TextAnalysisResult` (`text_analysis.py`): 워드클라우드, TF-IDF, 토픽, 감성 결과
- `classify_users()` (`user_classification.py`): 14개 피처 + K-Means 클러스터링

## Frontend

- D3.js v7 (CDN) + Chart.js v4 (CDN), 3탭 대시보드
- **네트워크 탭**: force-directed 그래프, hover 하이라이트, 커뮤니티 범례, ego 뷰 + 사이드 패널
- **텍스트 분석 탭**: 워드클라우드, TF-IDF 막대, LDA stacked area, 감성 bar chart
- **유저 유형 탭**: 클러스터 레이더 비교, 필터, 유저 카드 + 미니 레이더
- 다크 테마 (GitHub Dark 기반), 커뮤니티별 10색 팔레트
- 상태 폴링으로 백그라운드 분석 완료 시 자동 초기화
