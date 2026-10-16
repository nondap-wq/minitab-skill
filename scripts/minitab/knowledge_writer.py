"""Layer 5 - knowledge write-back."""

from __future__ import annotations

import re

from .com_executor import ExecutionResult
from .intent_parser import MinitabIntent
from .knowledge_base import ExperienceRecord, KnowledgeBase, PitfallRecord

ROOT_CAUSE_HINTS = (
    (r"cannot load type library|cantloadlibrary|CANTLOADLIBRARY|8002801C", "类型库无法解析（Minitab 17 私有 typelib 格式）"),
    (r"server execution failed|CO_E_SERVER_EXEC_FAILURE|80080005", "COM 服务器进程启动失败（Minitab 崩溃或需要管理员权限）"),
    (r"class not registered|80040154", "Mtb.Application 未注册"),
    (r"syntax|syntax error|ParseValidation", "会话命令语法错误（子命令分隔符或句点缺失）"),
    (r"column.*(not found|invalid)|does not exist", "引用了不存在的数据列"),
    (r"missing value|\\*", "数据包含缺失值，命令需要成对/完整数据"),
)


class KnowledgeWriter:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    @staticmethod
    def _pattern(result: ExecutionResult) -> str:
        err = result.error or ""
        err = re.sub(r"0x[0-9A-Fa-f]{4,8}", "0xHRESULT", err)
        return err[:180] or "unknown"

    @staticmethod
    def _root_cause(result: ExecutionResult) -> str:
        blob = f"{result.error or ''} {result.diagnosis.get('name', '')}"
        for pat, cause in ROOT_CAUSE_HINTS:
            if re.search(pat, blob, re.I):
                return cause
        return result.diagnosis.get("cause", "待分析")

    def write_after_execution(
        self,
        raw_input: str,
        intent: MinitabIntent,
        generated_code: str,
        commands: list[str],
        result: ExecutionResult,
    ) -> dict:
        record = ExperienceRecord(
            raw_input=raw_input,
            parsed_intent=intent.to_dict(),
            session_commands=commands,
            generated_code=generated_code,
            command_used="; ".join(commands)[:500],
            execution_result=str(result.to_dict())[:1000],
            success=result.success,
            dry_run=result.simulated,
            execution_time_ms=result.time_ms,
            error_message=result.error,
            tags=",".join([intent.analysis_category] + list(intent.constraints)),
        )
        rid = self.kb.write_experience(record)

        pitfall_id = None
        if not result.success and not result.simulated:
            first = (commands[0] if commands else intent.session_command) or ""
            pitfall_id = self.kb.write_pitfall(
                PitfallRecord(
                    command=first.split()[0] if first else "",
                    error_pattern=self._pattern(result),
                    root_cause=self._root_cause(result),
                    solution=result.diagnosis.get("solution", "待补充"),
                )
            )
        else:
            first = (commands[0] if commands else intent.session_command) or ""
            if first:
                self.kb.update_reliability(first.split()[0], success=result.success)
        return {"experience_id": rid, "pitfall_id": pitfall_id, "simulated": result.simulated}
