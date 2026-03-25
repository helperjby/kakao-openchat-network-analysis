import os
from pathlib import Path

# 데이터베이스
DB_PATH = os.getenv(
    "CHAT_DB_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "MiruBot" / "server" / "data" / "chat.db"),
)

# 분석 대상 채널
CHANNEL_ID = os.getenv("CHANNEL_ID", "18301468764762222")

# 상호작용 추론 파라미터
TIME_WINDOW_MS = 3 * 60 * 1000          # 3분
WEIGHT_TEMPORAL = 1.0                     # 시간 근접성 가중치
WEIGHT_MENTION = 3.0                      # @멘션 가중치
WEIGHT_NICKNAME = 2.0                     # LLM 닉네임 매핑 가중치

# 시각화
EDGE_PERCENTILE = 80                      # 상위 N% 엣지만 표시

# LLM 닉네임 매핑 캐시
NICKNAME_CACHE_PATH = str(Path(__file__).resolve().parent.parent / "data" / "nickname_map.json")

# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
