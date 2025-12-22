# ollama_client.py
import subprocess
import re
from config import OLLAMA_MODEL

def run_ollama_sync(prompt: str) -> str:
    """同步调用本地 ollama 模型"""
    try:
        # 增加 encoding='utf-8' 防止 Windows 下编码错误
        result = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True  # 增加 check=True 以便捕获错误
        )
        # 解析输出
        output = result.stdout.decode("utf-8").strip()
        
        # ----------------------------------------------------
        # 🔥 核心修復：使用正则删除思考过程，而不是只取最后一行
        # ----------------------------------------------------
        # 1. 匹配 Thinking... (换行) ...done thinking.
        output = re.sub(r'Thinking\.\.\..*?\.\.\.done thinking\.', '', output, flags=re.DOTALL).strip()
        
        # 2. 兼容 DeepSeek/Qwen 等模型的 <think> 标签
        output = re.sub(r'<think>.*?</think>', '', output, flags=re.DOTALL).strip()
        
        return output

    except subprocess.CalledProcessError as e:
        print(f"Ollama 调用失败: {e.stderr.decode('utf-8')}")
        return ""
    except Exception as e:
        print(f"发生未知错误: {str(e)}")
        return ""