# prompt_builder.py
from typing import List, Dict
import json

def build_prompt(user_input: str, memories: List[Dict]) -> str:
    """
    根据用户输入和角色记忆，构建适合 Ollama 的 Prompt
    """
    # 提取记忆内容和类型
    memory_texts = []
    for mem in memories:
        content = mem["content"]
        mem_type = mem["metadata"]["type"]
        memory_texts.append(f"[{mem_type}]: {content}")

    # 构建完整 Prompt
    prompt = f"""
    你是一个 AI 助手，基于以下记忆回答问题：
    {''.join(memory_texts)}
    
    用户输入: {user_input}
    请生成自然、简洁的回答。
    """
    return prompt
