# HANDOFF — 카카오톡 오픈채팅 네트워크 분석

> 마지막 업데이트: 2026-03-25
> 작업 환경: Windows 로컬 (`C:\Users\st016\OneDrive\project\04_2026\07. kakao openchat analysis`)
> GitHub: `https://github.com/helperjby/kakao-openchat-network-analysis`

## 프로젝트 개요

카카오톡 수다방(오픈채팅) 소셜 네트워크 분석 웹 애플리케이션.
2025년 데이터 기준 124만 메시지 / 46명 유저 / 12개월 분석.

FastAPI 백엔드 + D3.js & Chart.js 프론트엔드.
네트워크 분석 + 텍스트 분석(워드클라우드, TF-IDF, LDA, 감성) + 유저 유형 분류.

## 아키텍처

```
[chat.db] --> [analysis.py: 전처리+그래프] --> [NetworkAnalysisResult] (메모리 캐시)
                                                      |
         [text_analysis.py: NLP 파이프라인] --> [TextAnalysisResult] (pickle 캐시)
         [user_classification.py: K-Means]  --> [유저 유형 분류]     (pickle 캐시)
                                                      |
         [main.py: FastAPI 12개 라우트] <--------------+
                    |
         [static/: D3.js + Chart.js 3탭 대시보드]
```

## 파일 구조

| 파일 | 설명 |
|------|------|
| `app/config.py` | DB 경로, 2025 날짜 필터, 가중치, Gemini API, 캐시 경로 |
| `app/analysis.py` | 전처리, 엣지 구성, NetworkX 그래프, 중심성 4종, Louvain 커뮤니티 |
| `app/nickname_mapper.py` | Gemini 닉네임 매핑 + CSV 편집 가능 출력 + JSON 캐싱 |
| `app/text_analysis.py` | kiwipiepy 토큰화, 워드클라우드, TF-IDF, LDA, KNU 감성 + Gemini 보정 |
| `app/user_classification.py` | 14개 피처 추출 + K-Means 클러스터링 + 자동 라벨링 |
| `app/main.py` | FastAPI 서버, startup에서 네트워크 분석 + 백그라운드 텍스트/분류 |
| `static/index.html` | 3탭 레이아웃 (네트워크/텍스트/유저유형) |
| `static/style.css` | GitHub Dark 테마, 범례, 카드, 차트 스타일 |
| `static/app.js` | D3.js 그래프 + Chart.js 차트 + 상태 폴링 + 자동 초기화 |
| `data/knu_sentiment.json` | 한국어 감성사전 208단어 (긍정 101 / 부정 107) |
| `data/nickname_map.json` | Gemini 닉네임 매핑 캐시 (자동 생성) |
| `data/nickname_map_review.csv` | 편집 가능한 닉네임 매핑 (Excel로 열기) |
| `data/cache/` | pickle 캐시 (토큰, TF-IDF, 토픽, 감성, 유저분류) + 워드클라우드 PNG |

## API 엔드포인트

| 경로 | 설명 |
|------|------|
| `GET /` | 메인 대시보드 |
| `GET /api/network` | 전체 네트워크 그래프 JSON |
| `GET /api/users?q=` | 유저 검색 |
| `GET /api/user/{id}` | ego 네트워크 + 상세 정보 |
| `GET /api/text/wordcloud/{id}` | 유저별 워드클라우드 PNG |
| `GET /api/text/tfidf?scope=user&id=X` | TF-IDF 특징 단어 |
| `GET /api/text/topics` | LDA 토픽 + 월별 추이 |
| `GET /api/text/sentiment` | 감성 분석 (유저/커뮤니티/월별) |
| `GET /api/user-types` | 유저 유형 분류 결과 |
| `GET /api/analysis-status` | 분석 진행 상태 |

## 2025년 분석 결과 요약

| 항목 | 값 |
|------|------|
| 총 메시지 (2025) | 1,243,505 |
| 노이즈 필터링 후 | 938,222 (75.4%) |
| 유저 수 | 46명 |
| 엣지 수 | 966 |
| 커뮤니티 수 | 4 |
| Modularity | 0.0335 |
| 네트워크 분석 시간 | ~16초 |
| 텍스트 분석 시간 | ~17초 (캐시 사용 시) |
| LDA 토픽 | 10개 |
| 유저 유형 클러스터 | 4개 |
| Gemini 닉네임 매핑 | 7개 |
| 감성: 연간 긍정 비율 | 53~69% (7월 최고, 12월 최저) |

## 의존성

```
fastapi, uvicorn, networkx, pandas, numpy, requests, python-dotenv,
scipy, kiwipiepy, wordcloud, matplotlib, scikit-learn
```

Python 3.13 / Windows 10

## 실행

```bash
cd "C:\Users\st016\OneDrive\project\04_2026\07. kakao openchat analysis"
python -m uvicorn app.main:app --reload --port 8001
# http://localhost:8001
```

## 닉네임 매핑 편집

1. `data/nickname_map_review.csv`를 Excel로 열기
2. `approved` 컬럼을 `TRUE`/`FALSE`로 편집
3. 행 추가/삭제 가능
4. 서버 재시작 시 CSV 우선 로드

## 데이터 갱신

```bash
scp jby@192.168.0.133:/home/jby/MiruBot/server/data/chat.db* data/
rm -rf data/cache/  # 캐시 삭제 후 서버 재시작
```
