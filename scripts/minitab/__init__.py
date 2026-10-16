"""Minitab COM automation AI skill.

执行架构（自上而下，逐级兜底）::

    Stage 1  macro_library   -> 官方宏库检索（skill/macros，官方宏带索引）
    Stage 2  macro_generator -> 宏不存在时生成参数化 GMACRO 宏文件
    Stage 3  router          -> 决策：official_macro / generated_macro / com
    Stage 4  doe_rsm         -> COM 直控（会话命令、异步提交+完成门控、Minitab 原生出图）
    Stage 5  knowledge_base  -> 经验/避坑回写（SQLite）
    Stage 6  报告交付         -> Minitab 输出原文 + Minitab 原生图表

原有五层（intent_parser / knowledge_base / code_generator / com_executor /
knowledge_writer）保持不变，COM 链路是已验证的兜底通路。
"""

from .knowledge_base import KnowledgeBase, ExperienceRecord, PitfallRecord
from .intent_parser import MinitabIntent, RuleIntentParser, LLMIntentParser
from .code_generator import MinitabCodeGenerator
from .com_executor import ComBackend, DryRunBackend, ReplayBackend, doctor, select_backend, explain_hresult
from .knowledge_writer import KnowledgeWriter
from .orchestrator import MinitabAISkill, SkillRun

# 宏优先路由层（新增，不改动上方链路）
from . import macro_library, macro_generator, router
from .router import route, route_from_text, RouteDecision

__all__ = [
    "KnowledgeBase",
    "ExperienceRecord",
    "PitfallRecord",
    "MinitabIntent",
    "RuleIntentParser",
    "LLMIntentParser",
    "MinitabCodeGenerator",
    "ComBackend",
    "DryRunBackend",
    "ReplayBackend",
    "doctor",
    "select_backend",
    "explain_hresult",
    "KnowledgeWriter",
    "MinitabAISkill",
    "SkillRun",
    "macro_library",
    "macro_generator",
    "router",
    "route",
    "route_from_text",
    "RouteDecision",
]
__version__ = "0.2.0"
