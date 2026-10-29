"""Layer 4 - Minitab COM execution layer.

Backends
--------
* ComBackend   : real win32com automation (early binding via gencache, dynamic fallback)
* DryRunBackend: deterministic simulated execution (no Minitab required)
* ReplayBackend: replays a captured JSON transcript (used for offline verification)

The backend is chosen by `select_backend()`; the CLI exposes it as --backend.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# COM / Minitab error catalogue (see framework spec section 2.4)
TRACE_FILE = Path(os.environ.get("MINITAB_TRACE", Path(__file__).resolve().parent.parent.parent / "runtime" / "evidence" / "com_trace.log"))

ERROR_MAP: dict[int, dict[str, str]] = {
    0x800401E3: {
        "name": "MK_E_UNAVAILABLE",
        "cause": "Minitab 未在运行对象表中（未启动或未启用 COM 自动化）",
        "solution": "启动 Minitab 并勾选 工具>选项>OLE/COM>Enable Automation；确认许可证含 COM 模块",
    },
    0x80080005: {
        "name": "CO_E_SERVER_EXEC_FAILURE",
        "cause": "COM 服务器进程启动失败（Minitab 启动即崩溃，或需要管理员权限）",
        "solution": "先手动以管理员身份启动 Minitab 并确认窗口正常出现；查看应用事件日志中 Mtb.exe 的崩溃模块",
    },
    0x80040154: {
        "name": "REGDB_E_CLASSNOTREG",
        "cause": "Mtb.Application 未注册（Minitab 未安装或安装损坏）",
        "solution": "以管理员身份运行 Mtb.exe /regserver 或修复安装 Minitab",
    },
    0x8002801D: {
        "name": "TYPE_E_LIBNOTREGISTERED",
        "cause": "类型库未注册（旧版 Minitab 把 typelib 以私有格式写进 Mtb.exe，新 Windows 无法解析）",
        "solution": "使用 Minitab 20/21/22（ProgID 仍为 Mtb.Application，typelib 为标准 MSFT 格式）",
    },
    0x8002801C: {
        "name": "TYPE_E_CANTLOADLIBRARY",
        "cause": "无法从注册路径加载类型库（Minitab 17 及更早版本的典型症状）",
        "solution": "升级到 Minitab 20+；或改用 late-binding 并接受无法按名称解析成员",
    },
    0x80020003: {
        "name": "DISP_E_MEMBERNOTFOUND",
        "cause": "会话命令或属性名不存在",
        "solution": "用 minitab CLI 的 kb --command 查询命令模板，或核对命令拼写与版本",
    },
    0x80020009: {
        "name": "DISP_E_EXCEPTION",
        "cause": "Minitab 执行会话命令时抛出异常（语法错误/数据不满足要求）",
        "solution": "检查命令语法（子命令以 ; 开头、以 . 结尾）与数据列是否存在",
    },
}


def _hresult_of(exc: BaseException) -> int | None:
    """Extract an HRESULT from pywin32/comtypes exceptions or nested causes."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        for candidate in (getattr(cur, "hresult", None), (cur.args[0] if cur.args else None)):
            if isinstance(candidate, int) and candidate != 0:
                return candidate
        cur = cur.__cause__ or cur.__context__
    return None


def explain_hresult(hr: int | None) -> dict[str, str]:
    if hr is None:
        return {}
    hr &= 0xFFFFFFFF
    return ERROR_MAP.get(hr, {"name": f"0x{hr:08X}", "cause": "未收录的 HRESULT", "solution": "记录到避坑库后人工分析"})


@dataclass
class ExecutionResult:
    success: bool
    commands: list[str]
    outputs: list[dict] = field(default_factory=list)
    error: str | None = None
    hresult: int | None = None
    diagnosis: dict[str, str] = field(default_factory=dict)
    time_ms: int = 0
    backend: str = "com"
    simulated: bool = False
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "commands": self.commands,
            "outputs": self.outputs,
            "error": self.error,
            "hresult": None if self.hresult is None else f"0x{self.hresult & 0xFFFFFFFF:08X}",
            "diagnosis": self.diagnosis,
            "time_ms": self.time_ms,
            "backend": self.backend,
            "simulated": self.simulated,
            "artifacts": self.artifacts,
        }


class Backend(Protocol):
    name: str

    def execute(self, commands: list[str], project: str = "", output_dir: str = "") -> ExecutionResult: ...


# --------------------------------------------------------------------- dry run
def _synthetic_outputs(commands: list[str]) -> list[dict]:
    outs: list[dict] = []
    for cmd in commands:
        head = cmd.strip().split()[0].upper()
        if head in ("CAPA", "CAPABILITY"):
            outs.append(
                {
                    "type": "table",
                    "title": "Process Capability Report",
                    "rows": [
                        ["Cp", "1.31"], ["CPL", "1.22"], ["CPU", "1.40"],
                        ["Cpk", "1.22"], ["Pp", "1.28"], ["Ppk", "1.19"],
                    ],
                }
            )
        elif head == "DESCRIBE":
            outs.append(
                {
                    "type": "table",
                    "title": "Descriptive Statistics",
                    "rows": [["N", "10"], ["Mean", "13.0"], ["StDev", "1.94"], ["Minimum", "10.0"], ["Maximum", "16.0"]],
                }
            )
        elif head in ("XBR", "XBAR"):
            outs.append({"type": "graph", "title": "Xbar-R Chart", "rows": [["UCL", "17.4"], ["CL", "13.0"], ["LCL", "8.6"]]})
        elif head == "NOTE":
            outs.append({"type": "paragraph", "title": "Note", "text": cmd[4:].strip()})
        else:
            outs.append({"type": "paragraph", "title": head, "text": f"simulated output for: {cmd}"})
    return outs


class DryRunBackend:
    name = "dry-run"

    def execute(self, commands: list[str], project: str = "", output_dir: str = "") -> ExecutionResult:
        t0 = time.time()
        return ExecutionResult(
            success=True,
            commands=commands,
            outputs=_synthetic_outputs(commands),
            time_ms=int((time.time() - t0) * 1000),
            backend=self.name,
            simulated=True,
        )


class ReplayBackend:
    """Replays a captured transcript produced by a real Minitab session."""

    name = "replay"

    def __init__(self, transcript: str | Path):
        self.transcript = Path(transcript)
        self.data = json.loads(self.transcript.read_text(encoding="utf-8"))

    def execute(self, commands: list[str], project: str = "", output_dir: str = "") -> ExecutionResult:
        res = ExecutionResult(
            success=bool(self.data.get("success")),
            commands=commands,
            outputs=self.data.get("outputs", []),
            error=self.data.get("error"),
            time_ms=int(self.data.get("time_ms", 0)),
            backend=self.name,
            simulated=True,
        )
        res.hresult = int(self.data["hresult"], 16) if self.data.get("hresult") else None
        return res


# ------------------------------------------------------------------- real COM
class ComBackend:
    name = "com"

    def __init__(
        self,
        visible: bool = True,
        quit_when_launched: bool = False,
        retries: int = 1,
        sample_data: bool = False,
        sample_rows: int = 30,
        export_outputs_enabled: bool = False,
    ):
        self.visible = visible
        self.quit_when_launched = quit_when_launched
        self.retries = retries
        self.sample_data = sample_data
        self.sample_rows = sample_rows
        # SaveAs on a live session can block on dialogs; export stays opt-in.
        self.export_outputs_enabled = export_outputs_enabled
        self._app = None
        self._project = None
        self._launched = False
        self._data_loaded = False

    # -------------------------------------------------------------- test data
    def _ensure_data(self) -> list[str]:
        """Insert a deterministic numeric sample dataset so commands referencing C1/C2
        always have data. Numeric only: writing text into a fresh column blocks the
        COM call on Minitab 22 (observed hang), so text demo columns are avoided."""
        if not self.sample_data or self._data_loaded:
            return []
        ws = self._project.ActiveWorksheet
        rows = max(10, int(self.sample_rows))
        # deterministic pattern: thickness around 13 with a slow drift
        thickness = [round(13.0 + ((i % 7) - 3) * 0.9 + (i // 7) * 0.15, 3) for i in range(rows)]
        doubled = [round(v * 2, 3) for v in thickness]
        setup = []
        for idx, (name, values) in enumerate((("Thickness", thickness), ("Double", doubled)), start=1):
            while ws.Columns.Count < idx:
                ws.Columns.Add()
            col = ws.Columns.Item(idx)
            col.SetData(values, 1, len(values))
            col.Name = name
            setup.append(f"C{idx} = {name} ({len(values)} numeric rows)")
        self._data_loaded = True
        return setup

    # ------------------------------------------------------------- connection
    def connect(self) -> None:
        import pythoncom  # local import: only needed for the COM backend
        import win32com.client
        from win32com.client import gencache

        self._trace("connect: CoInitialize")
        pythoncom.CoInitialize()
        self._launched = not self._minitab_running()
        self._trace(f"connect: minitab_running={not self._launched}")
        last: Exception | None = None
        for attempt in range(1, self.retries + 2):
            self._trace(f"connect: dispatch attempt {attempt}")
            for factory in (
                lambda: gencache.EnsureDispatch("Mtb.Application"),
                lambda: win32com.client.dynamic.Dispatch("Mtb.Application"),
            ):
                try:
                    self._app = factory()
                    break
                except Exception as exc:  # noqa: BLE001
                    last = exc
            if self._app is not None:
                break
            time.sleep(2 * attempt)
        if self._app is None:
            raise RuntimeError(f"无法连接 Mtb.Application: {last!r}")
        self._trace("connect: dispatch ok")

        try:
            if self.visible:
                self._trace("connect: set Visible")
                self._app.UserInterface.Visible = True
                self._trace("connect: Visible ok")
        except Exception as exc:  # noqa: BLE001
            self._trace(f"connect: Visible skipped ({exc!r})")
        # DisplayAlerts 必须保持 True。设 False 会吞掉错误报告，出错命令留下的未决状态
        # 会把命令队列永久卡死（后续一律报"正忙于处理操作"）；保持 True 时错误会以
        # 'Syntax Error' 登记为命令名，可据此逐条迭代语法。
        try:
            self._app.UserInterface.DisplayAlerts = True
            self._app.UserInterface.Interactive = True
            self._trace("connect: DisplayAlerts=True")
        except Exception as exc:  # noqa: BLE001
            self._trace(f"connect: DisplayAlerts skipped ({exc!r})")
        if self.visible:
            # 无头模式下命令会被静默丢弃；给窗口留出初始化时间
            self._trace("connect: wait for UI init")
            time.sleep(3)
        try:
            self._trace("connect: ActiveProject")
            self._project = self._app.ActiveProject
            if self._project is None:
                self._trace("connect: New()")
                self._app.New()
                self._project = self._app.ActiveProject
            self._trace("connect: project ok")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"无法获取 ActiveProject: {exc!r}") from exc

    def _trace(self, msg: str) -> None:
        try:
            with open(TRACE_FILE, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _minitab_running() -> bool:
        if os.name != "nt":
            return False
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Mtb.exe", "/NH"],
                capture_output=True, text=True, timeout=15,
            ).stdout or ""
            return "Mtb.exe" in out
        except Exception:  # noqa: BLE001
            return False

    # -------------------------------------------------------------- execution
    def execute(self, commands: list[str], project: str = "", output_dir: str = "") -> ExecutionResult:
        t0 = time.time()
        cmds = list(commands)
        if project:
            cmds.insert(0, f"RETRIEVE '{project}'")
        try:
            try:
                if self._app is None:
                    self.connect()
            except Exception as conn_exc:  # noqa: BLE001
                hr = _hresult_of(conn_exc)
                return ExecutionResult(
                    success=False,
                    commands=cmds,
                    error=f"{type(conn_exc).__name__}: {conn_exc}",
                    hresult=hr,
                    diagnosis=explain_hresult(hr),
                    time_ms=int((time.time() - t0) * 1000),
                    backend=self.name,
                )
            if project and self._app is not None:
                try:
                    self._app.Open(project)
                    self._project = self._app.ActiveProject
                    cmds = [c for c in cmds if not c.upper().startswith("RETRIEVE")]
                except Exception:  # noqa: BLE001
                    pass
            setup = self._ensure_data() if self.sample_data else []
            statuses = []
            for cmd in cmds:
                # Commands WITH subcommands must arrive as ONE string using ';' separators and
                # a trailing '.' (verified on Minitab 22). Never split them across calls.
                self._project.ExecuteCommand(cmd)
                statuses.append({"command": cmd, "ok": True})
            outputs = self.capture_outputs()
            if setup:
                outputs.insert(0, {"type": "setup", "title": "sample data loaded", "text": "; ".join(setup)})
            artifacts = {}
            if output_dir and self.export_outputs_enabled:
                artifacts = self.export_outputs(output_dir)
            return ExecutionResult(
                success=True,
                commands=cmds,
                outputs=outputs,
                time_ms=int((time.time() - t0) * 1000),
                backend=self.name,
                artifacts=artifacts,
            )
        except Exception as exc:  # noqa: BLE001
            hr = _hresult_of(exc)
            return ExecutionResult(
                success=False,
                commands=cmds,
                error=f"{type(exc).__name__}: {exc}",
                hresult=hr,
                diagnosis=explain_hresult(hr),
                time_ms=int((time.time() - t0) * 1000),
                backend=self.name,
            )

    def capture_outputs(self) -> list[dict]:
        outs: list[dict] = []
        try:
            commands = self._project.Commands
            n = commands.Count
            if not n:
                return outs
            # IOutput exposes no OutputDocument on Minitab 22 (late binding); the command
            # Name carries the analysis title, e.g. "Thickness 的过程能力报告".
            for idx in range(max(1, n - 4), n + 1):
                cmd = commands.Item(idx)
                entry: dict = {"type": "command", "index": idx}
                for attr in ("Name", "CommandText"):
                    try:
                        entry[attr] = getattr(cmd, attr)
                        break
                    except Exception:  # noqa: BLE001
                        continue
                # 输出原文按版本取：Mtb 20 用 OutputDocument.Text（无 Outputs 属性）；
                # Mtb 22 旧记录用 Outputs.Item(k).Text。先试前者，再回退。
                try:
                    od = cmd.OutputDocument
                    if od is not None:
                        txt = str(getattr(od, "Text", "") or "")
                        if txt.strip():
                            entry["text"] = txt
                            entry["text_source"] = "OutputDocument"
                except Exception:  # noqa: BLE001
                    pass
                try:
                    out_coll = cmd.Outputs
                    entry["outputs"] = out_coll.Count
                    names = []
                    for i in range(1, out_coll.Count + 1):
                        item = out_coll.Item(i)
                        for attr in ("Name", "Title"):
                            try:
                                names.append(getattr(item, attr))
                                break
                            except Exception:  # noqa: BLE001
                                continue
                    if names:
                        entry["output_names"] = names
                except Exception:  # noqa: BLE001
                    pass
                outs.append({k: v for k, v in entry.items() if v not in (None, "")})
        except Exception as exc:  # noqa: BLE001
            outs.append({"type": "warning", "text": f"capture_outputs failed: {exc!r}"})
        return outs

    def export_outputs(self, output_dir: str) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        d = Path(output_dir)
        d.mkdir(parents=True, exist_ok=True)
        try:
            target = d / "minitab_output"
            self._project.SaveAs(str(target), True, 22)
            artifacts["project"] = str(target)
        except Exception as exc:  # noqa: BLE001
            artifacts["error"] = f"SaveAs failed: {exc!r}"
        return artifacts

    def shutdown(self) -> None:
        try:
            if self._app is not None and self.quit_when_launched and self._launched:
                self._app.Quit()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._app = None
            self._project = None
            try:
                import pythoncom

                pythoncom.CoUninitialize()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- preflight
def doctor() -> dict:
    """Environment report + remediation. Safe to run anywhere."""
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "python_bits": 64 if sys.maxsize > 2**32 else 32,
        "registrations": {},
        "typelib": {},
        "server": {},
        "ready": False,
        "remediation": [],
    }
    try:
        import winreg
    except ImportError:
        info["remediation"].append("winreg 不可用：非 Windows 环境无法使用 COM")
        return info

    def reg_value(path, name="", hive=None):
        """Read a registry value, trying the 64-bit then the 32-bit view."""
        hive = hive or winreg.HKEY_LOCAL_MACHINE
        for flag in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for root in (hive, winreg.HKEY_CLASSES_ROOT):
                try:
                    with winreg.OpenKey(root, path, 0, winreg.KEY_READ | flag) as k:
                        return winreg.QueryValueEx(k, name)[0]
                except OSError:
                    continue
        return None

    clsid = reg_value(r"SOFTWARE\Classes\Mtb.Application\CLSID")
    info["registrations"]["Mtb.Application CLSID"] = clsid
    if clsid:
        server = reg_value(rf"SOFTWARE\Classes\CLSID\{clsid}\LocalServer32")
        typelib = reg_value(rf"SOFTWARE\Classes\CLSID\{clsid}\TypeLib")
        info["server"] = {"LocalServer32": server}
        info["typelib"]["libid"] = typelib
        if server:
            exe = server.strip('"').split('"')[0]
            if Path(exe).exists():
                try:
                    import re as _re

                    txt = Path(exe).read_bytes()
                    m = _re.search(rb"FileVersion\x00+([0-9., ]+)", txt)
                    m2 = _re.search(rb"ProductVersion\x00+([0-9., ]+)", txt)
                    info["server"]["file_version"] = (m.group(1) if m else b"").decode("latin-1", "ignore").strip("\x00 ")
                    info["server"]["product_version"] = (m2.group(1) if m2 else b"").decode("latin-1", "ignore").strip("\x00 ")
                except Exception:  # noqa: BLE001
                    pass
        if typelib:
            reg_path = rf"SOFTWARE\Classes\TypeLib\{typelib}\1.0"
            info["typelib"].update(
                {
                    "name": reg_value(reg_path),
                    "win32": reg_value(reg_path + r"\0\win32"),
                    "win64": reg_value(reg_path + r"\0\win64"),
                }
            )
    else:
        info["remediation"].append("Mtb.Application 未注册：安装 Minitab 或运行 Mtb.exe /regserver")

    # try loading the typelib and creating the object
    try:
        import pythoncom
        import pywintypes

        pythoncom.CoInitialize()
        lib = None
        if info["typelib"].get("libid"):
            try:
                lib = pythoncom.LoadRegTypeLib(pywintypes.IID(info["typelib"]["libid"]), 1, 0)
                info["typelib"]["loadable"] = True
                info["typelib"]["types"] = lib.GetTypeInfoCount()
            except Exception as exc:  # noqa: BLE001
                info["typelib"]["loadable"] = False
                info["typelib"]["load_error"] = repr(exc)
        else:
            info["typelib"]["loadable"] = False
        if clsid:
            try:
                import win32com.client

                app = win32com.client.dynamic.Dispatch("Mtb.Application")
                _ = app.ActiveProject  # force a real member call
                info["server"]["dispatch"] = "ok"
                info["ready"] = True
            except Exception as exc:  # noqa: BLE001
                hr = _hresult_of(exc)
                info["server"]["dispatch"] = f"fail: {exc!r}"
                info["server"]["hresult"] = f"0x{hr & 0xFFFFFFFF:08X}" if hr is not None else None
                info["server"]["diagnosis"] = explain_hresult(hr)
                version = str(info["server"].get("product_version") or "")
                if not info["typelib"].get("loadable"):
                    if version[:2] in ("17", "16", "15"):
                        info["remediation"].append(
                            f"检测到 Minitab {version}：该版本把自动化 typelib 写成了 Windows 无法解析的私有格式，"
                            "请升级到 Minitab 20/21/22（ProgID 仍为 Mtb.Application）"
                        )
                    else:
                        info["remediation"].append(
                            "类型库注册存在但不可加载：以管理员身份运行 "
                            f"\"{info['server'].get('LocalServer32','Mtb.exe')}\" /regserver 修复注册"
                        )
                if hr == 0x80080005:
                    info["remediation"].append(
                        "COM 服务器进程启动失败：请手动以管理员身份启动 Minitab 并确认主窗口正常出现；"
                        "若启动即崩溃，查看 事件查看器>应用程序 中 Mtb.exe 的崩溃模块（如 libcef.dll）"
                    )
    except ImportError:
        info["remediation"].append("未安装 pywin32：pip install pywin32（32 位 Minitab 需 32 位 Python）")

    if not info["ready"] and not info["remediation"]:
        info["remediation"].append("以管理员身份手动启动 Minitab，确认窗口出现后重试；并启用 工具>选项>OLE/COM>Enable Automation")
    return info


def select_backend(kind: str, **kwargs) -> Backend:
    kind = (kind or "auto").lower()
    if kind == "dry-run":
        return DryRunBackend()
    if kind == "replay":
        return ReplayBackend(kwargs["transcript"])
    if kind == "com":
        return ComBackend(**{k: v for k, v in kwargs.items() if k in ("visible", "quit_when_launched", "retries")})
    # auto: use COM when the environment is ready, otherwise fall back to dry-run
    report = doctor()
    if report.get("ready"):
        return ComBackend(visible=kwargs.get("visible", True))
    return DryRunBackend()
