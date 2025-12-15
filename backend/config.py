OLLAMA_MODEL = "qwen3:14b"
CHROMA_DB_DIR = "memory_db"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
MAX_MEMORY_TO_FEED = 8
MIN_TOKEN_LEN_TO_STORE = 6

# 在 config.py 中修改
from datetime import datetime, timezone, timedelta

# 创建中国时区（UTC+8）
CHINA_TZ = timezone(timedelta(hours=8))

# 定义全局起始时间（中国时间）
START_TIME = datetime(2025, 12, 14, 16, 0, 0, tzinfo=CHINA_TZ)
