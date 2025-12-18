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
# prompt_builder.py

def build_prompt(user_input: str, memories: List[Dict], available_targets: List[str]) -> str:
    # 构造可交互目标清单
    targets_str = "、".join(available_targets)
    
    tools_section = f"""
    ### 动作执行指南
    你可以通过输出以下格式的 JSON 来控制角色动作（每次回复限一个动作）：
    JSON_START {{"action": "move", "target": "目标名称"}} JSON_END
    
    当前环境可移动到的目标：[{targets_str}]
    """
    
    # 之前的记忆提取逻辑...
    memory_texts = "\n".join([f"[{m['metadata']['type']}]: {m['content']}" for m in memories])

    prompt = f"""
    {tools_section}
    
    ### 环境与记忆
    {memory_texts}
    
    ### 任务
    用户对你说："{user_input}"
    请以角色的身份进行对话，并在必要时附带动作 JSON。
    """
    return prompt