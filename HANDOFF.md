# HANDOFF — 카카오톡 오픈채팅 네트워크 분석

> 마지막 업데이트: 2026-03-25
> 작업 환경: Raspberry Pi (`/home/jby/chat-network-analysis/`)
> 목표 실행 환경: Windows 로컬 (`C:\Users\st016\OneDrive\project\04_2026\07. kakao openchat analysis`)

## 프로젝트 개요

카카오톡 수다방(오픈채팅) 167만 메시지, 55명 유저, 15개월 데이터로 소셜 네트워크 분석을 수행하는 웹 애플리케이션.
FastAPI 백엔드 + D3.js 프론트엔드로 인터랙티브 네트워크 시각화 제공.

## 완료된 작업

### 코드 구현 (전체 완료)

| 파일 | 상태 | 설명 |
|------|------|------|
| `app/config.py` | ✅ 완료 | DB 경로, 채널 ID, 가중치 설정, Gemini API 설정 |
| `app/analysis.py` | ✅ 완료 | 전처리, 엣지 구성, NetworkX 그래프, 중심성, 커뮤니티 탐지 |
| `app/nickname_mapper.py` | ✅ 완료 | Gemini API로 비공식 닉네임→실제 유저 매핑, JSON 캐싱 |
| `app/main.py` | ✅ 완료 | FastAPI 라우트 4개 (/, /api/network, /api/users, /api/user/{id}) |
| `static/index.html` | ✅ 완료 | 검색바 + 그래프 영역 + 사이드 패널 레이아웃 |
| `static/style.css` | ✅ 완료 | 다크 테마, 반응형 |
| `static/app.js` | ✅ 완료 | D3.js force-directed 그래프, 전체 뷰/ego 뷰 전환, 검색 |
| `requirements.txt` | ✅ 완료 | fastapi, uvicorn, networkx, pandas, numpy, requests, python-dotenv |
| `.gitignore` | ✅ 완료 | data/, __pycache__/, .env 제외 |

### Git & GitHub

- 라즈베리파이에서 git init + 커밋 완료 (`932076d`)
- GitHub push 완료: `https://github.com/helperjby/kakao-openchat-network-analysis`
- 브랜치: `main`

### 데이터 탐색 결과

- **DB 위치**: 라즈베리파이 `/home/jby/MiruBot/server/data/chat.db` (~312MB)
  - Docker 볼륨 마운트로 호스트에 직접 존재 (추출 불필요)
  - WAL 파일: `chat.db-shm` (32KB), `chat.db-wal` (~4MB)
- **채널**: `18301468764762222` (수다방)
- **유저**: 55명, 모든 user_hash → 1개 user_name (닉변 없음)
- **메시지 간격**: 60%가 30초 이내 (매우 활발한 채팅방)
- **@멘션**: ~5,200건 존재 (명시적 방향 엣지로 활용)

### 분석 설계

상호작용 추론에 3가지 신호 결합:
1. **시간 근접성** (가중치 1.0) — 3분 이내 연속 메시지
2. **@멘션** (가중치 3.0) — `@username` 명시적 언급
3. **LLM 닉네임 매핑** (가중치 2.0) — Gemini로 비공식 별명 해석

노이즈 필터링 정규식은 MiruBot `server/app/services/stats_service.py` L11-19에서 가져옴.

## 실패한 것 / 미완료

### pip install 미실행
- 라즈베리파이에서 `pip install -r requirements.txt` 시도했으나 유저가 거부
- **이유**: 라즈베리파이에서 대용량 분석이 느릴 것으로 판단 → Windows 로컬로 이동 결정

### 서버 실행 테스트 미완료
- 코드가 실제로 동작하는지 아직 한 번도 실행하지 않음
- 잠재적 이슈:
  - import 오류 (의존성 간 호환성)
  - 167만 행 처리 시 메모리/시간 문제
  - D3.js 시뮬레이션 성능 (55노드는 문제없을 것으로 예상)
  - `python-dotenv` 로드: `nickname_mapper.py`에서 `.env` 파일 로드 안 함 → `config.py`에서 로드 필요할 수 있음

### LLM 닉네임 매핑 미테스트
- Gemini API 호출 코드는 작성했지만 실행 안 함
- `GEMINI_API_KEY` 없으면 빈 매핑으로 fallback (분석은 정상 진행)

## 다음 단계

### 1. Windows 로컬 환경 구축

```bash
# 1) clone
git clone https://github.com/helperjby/kakao-openchat-network-analysis.git "C:\Users\st016\OneDrive\project\04_2026\07. kakao openchat analysis"

# 2) chat.db 복사 (라즈베리파이에서)
scp jby@<PI_IP>:/home/jby/MiruBot/server/data/chat.db "./data/"
# 또는 chat.db-shm, chat.db-wal도 함께 복사하면 최신 데이터 보장

# 3) data 디렉토리 생성 (없으면)
mkdir data

# 4) 의존성 설치
pip install -r requirements.txt

# 5) (선택) .env 파일 생성 — LLM 닉네임 매핑을 사용하려면
echo GEMINI_API_KEY=your_key_here > .env

# 6) 서버 실행
uvicorn app.main:app --reload --port 8001

# 7) 브라우저에서 http://localhost:8001 접속
```

### 2. 첫 실행 후 예상 디버깅 포인트

- **`python-dotenv` 로딩**: `app/config.py` 상단에 `from dotenv import load_dotenv; load_dotenv()` 추가 필요할 수 있음
- **메모리**: 167만 행 pandas DataFrame이 ~500MB-1GB RAM 사용 가능. Windows에선 문제없을 것
- **분석 시간**: 서버 시작 시 1회 분석 실행. 예상 30초-2분 (CPU 성능 의존)
- **한글 인코딩**: Windows에서 SQLite 한글 처리는 보통 문제없음

### 3. 기능 검증 체크리스트

- [ ] `http://localhost:8001` 접속 → 전체 네트워크 그래프 표시
- [ ] 노드 hover → 툴팁 (이름, 메시지 수, PageRank)
- [ ] 노드 클릭 → ego 뷰 전환 + 사이드 패널 표시
- [ ] 검색바에 유저 이름 입력 → 자동완성 → 선택 시 ego 뷰
- [ ] "전체 네트워크" 버튼 → 전체 뷰 복귀
- [ ] 사이드 패널: 중심성 점수 4개 + 순위 + Top 대화 상대 + 커뮤니티 멤버

### 4. 향후 개선 가능 사항 (현재 스코프 밖)

- 시간대별 네트워크 변화 애니메이션
- 커뮤니티별 활동 시간대 히트맵
- 대화 내용 기반 토픽 분석
- 네트워크 통계 대시보드 (밀도, 평균 경로 길이 등)

## 핵심 아키텍처 참고

```
[chat.db] → [analysis.py: 전처리+그래프] → [메모리 캐시]
                                               ↓
[브라우저] ← [D3.js] ← [FastAPI API] ← [NetworkAnalysisResult]
```

- 서버 시작 시 `startup` 이벤트에서 전체 분석 1회 실행 → `NetworkAnalysisResult` 객체에 캐싱
- API는 캐싱된 결과만 반환 (요청마다 재계산하지 않음)
- `NetworkAnalysisResult.to_network_json()`: 전체 네트워크 JSON
- `NetworkAnalysisResult.get_ego_network(user_hash)`: 유저 중심 서브그래프 JSON
