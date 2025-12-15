# ollama_client.py
import subprocess
from config import OLLAMA_MODEL

def run_ollama_sync(prompt: str) -> str:
    """同步调用本地 ollama 模型"""
    result = subprocess.run(
        ["ollama", "run", OLLAMA_MODEL],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    # 解析输出
    output = result.stdout.decode("utf-8").strip()
    # 去掉多余 Thinking... 等文本
    if output.startswith("Thinking"):
        output = output.split("\n")[-1]
    return output
