"""Minitab AI Skill orchestrator - wires all five layers into one pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .code_generator import GenerationResult, MinitabCodeGenerator
from .com_executor import Backend, DryRunBackend, ExecutionResult, doctor, select_backend
from .intent_parser import LLMIntentParser, MinitabIntent, RuleIntentParser
from .knowledge_base import KnowledgeBase
from .knowledge_writer import KnowledgeWriter

DEFAULT_ROOT = Path(__file__).resolve().parent
DEFAULT_ARTIFACTS = DEFAULT_ROOT.parent.parent / "runtime" / "artifacts"


@dataclass
class SkillRun:
    user_input: str
    intent: dict
    generation: dict
    execution: dict
    knowledge: dict
    backend: str
    simulated: bool = False
    artifacts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "user_input": self.user_input,
            "intent": self.intent,
            "generation": self.generation,
            "execution": self.execution,
            "knowledge": self.knowledge,
            "backend": self.backend,
            "simulated": self.simulated,
            "artifacts": self.artifacts,
        }


class MinitabAISkill:
    def __init__(
        self,
        db_path: str | Path | None = None,
        backend: str | Backend = "auto",
        llm=None,
        artifact_dir: str | Path | None = None,
    ):
        self.kb = KnowledgeBase(db_path)
        self.parser = LLMIntentParser(llm) if llm else RuleIntentParser()
        self.generator = MinitabCodeGenerator(self.kb)
        self.writer = KnowledgeWriter(self.kb)
        self.artifact_dir = Path(artifact_dir) if artifact_dir else DEFAULT_ARTIFACTS
        if isinstance(backend, str):
            self._backend_kind = backend
            self.backend: Backend = DryRunBackend() if backend == "dry-run" else select_backend(backend)
        else:
            self._backend_kind = getattr(backend, "name", "custom")
            self.backend = backend

    # ------------------------------------------------------------------ public
    def plan(self, user_input: str) -> tuple[MinitabIntent, GenerationResult]:
        intent = self.parser.parse(user_input)
        # honour an explicit command override from the knowledge base (e.g. user pinned one)
        generation = self.generator.generate(intent)
        return intent, generation

    def run(
        self,
        user_input: str,
        project: str = "",
        output_dir: str | Path | None = None,
        write_script: bool = True,
    ) -> SkillRun:
        intent, gen = self.plan(user_input)
        out_dir = Path(output_dir) if output_dir else self.artifact_dir / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)

        script_path = None
        if write_script:
            script_path = self.generator.write_script(gen.python_code, out_dir / "generated_driver.py")

        result: ExecutionResult = self.backend.execute(gen.session_commands, project=project, output_dir=str(out_dir))
        knowledge = self.writer.write_after_execution(
            raw_input=user_input,
            intent=intent,
            generated_code=gen.python_code,
            commands=gen.session_commands,
            result=result,
        )
        artifacts = dict(result.artifacts)
        if script_path:
            artifacts["script"] = str(script_path)
        return SkillRun(
            user_input=user_input,
            intent=intent.to_dict(),
            generation={
                "session_commands": gen.session_commands,
                "command_used": gen.command_used,
                "rationale": gen.rationale,
                "context_used": gen.context_used,
            },
            execution=result.to_dict(),
            knowledge=knowledge,
            backend=result.backend,
            simulated=result.simulated,
            artifacts=artifacts,
        )

    def doctor(self) -> dict:
        return doctor()

    def shutdown(self) -> None:
        fn = getattr(self.backend, "shutdown", None)
        if callable(fn):
            fn()

    @staticmethod
    def dumps(run: SkillRun) -> str:
        return json.dumps(run.to_dict(), ensure_ascii=False, indent=1)
