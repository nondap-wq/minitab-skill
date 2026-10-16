# Evidence: Minitab 22 COM 试运行记录（D:\mechanic\minitab）

记录时间：2026-10（本机实测）
环境：Windows 11 (10.0.26200)，Minitab 22.1.0.0（`D:\Program Files\Minitab\Mtb.exe`），
Python 3.12.4 64-bit（`python`，pywin32 已安装）。

## 1. 类型库与注册（`minitab_cli.py doctor`）

| 项目 | 值 |
|---|---|
| `Mtb.Application` CLSID | `{6265486C-4A08-4B4E-9713-C2CD85F1F515}` |
| LocalServer32 | `"D:\Program Files\Minitab\Mtb.exe"` |
| TypeLib libid | `{0BC1FB77-06FC-418D-8005-D1942B1FA493}`（Mtb 20.0 Type Library） |
| win32/win64 | `D:\Program Files\Minitab\Mtb.exe\2` |
| `LoadRegTypeLib` | 成功，52 个类型 |
| `Dispatch("Mtb.Application")` | 成功（`READY: True`） |

对比：Minitab 17（`C:\Program Files (x86)\Minitab\Minitab 17\Mtb.exe`，typelib
`{0681D994-...}`）的 typelib 以私有 MSFT 变体写入 EXE 资源，`LoadTypeLib` 返回
`0x8002801C TYPE_E_CANTLOADLIBRARY`，外部 COM 客户端无法按名称解析成员 → **Minitab 17 不可自动化**（已实测，含 32/64 位 Python）。

## 2. 已跑通的 COM 基本能力（逐层验证）

| 步骤 | 结果 |
|---|---|
| `gencache.EnsureDispatch("Mtb.Application")` | OK（1.7 s） |
| `ActiveProject` / 新建项目 | OK |
| `ActiveWorksheet.Columns.Add()` + `Column.SetData(list, 1, n)` | OK（30 行数值列，0.01 s） |
| `Column.Name = "Thickness"` | OK |
| `ExecuteCommand("LET C2 = C1 * 2")` | OK |
| `ExecuteCommand("DESCRIBE C1 C2")` | OK |
| 读取 `Commands.Item(n).Outputs.Item(i).OutputDocument.Title` | OK |

## 3. 关键发现：多行会话命令必须逐行发送

`CAPABILITY` 这类带子命令的命令，**把多行拼成一个字符串**传给
`ExecuteCommand` 会让 COM 服务器永久挂起（实测 >5 min 无返回，进程仍 Responding，UI 无弹窗）：

```
ExecuteCommand("CAPABILITY C1;  LSL 9;  USL 17.")     -> 挂起（危险）
```

变体扫描结果（`probe/cap_variants.py`，每个变体独立子进程 + 45 s 超时）：

| 变体 | 结果 |
|---|---|
| `CAPABILITY C1` → `  LSL 9` → `  USL 17` → `.`（4 次调用，逐行） | **全部返回**（首行 26.9 s 为首次加载统计模块，后续 0.6–1.7 s） |
| `CAPABILITY C1;` + `  LSL 9;` + `  USL 17.`（3 次调用，逐行） | 未单独验证成功（该轮被前序挂起污染） |
| 单字符串合并发送（多种写法） | 全部挂起 |

**结论（已固化到实现）**：生成器 `split_command_lines()` 把逻辑命令展开为逐行执行；
执行器 `ComBackend.execute()` 对含 `\n` 的命令逐行发送。首次调用某个统计模块可能耗时
20–30 s，执行超时阈值不应低于 60 s。

## 4. 权限要求

非提权进程调用 `Dispatch("Mtb.Application")` 返回
`0x80080005 CO_E_SERVER_EXEC_FAILURE`（服务器进程启动失败）。提权进程可正常启动并连接
Minitab 22 的 COM 服务器。**结论：驱动 Minitab COM 的宿主进程需要管理员权限**
（与官方文档"以管理员身份启动 Minitab"一致）。

## 5. 复现命令

```powershell
$root = 'D:\mechanic\minitab\skill'
python "$root\scripts\minitab_cli.py" doctor
python "$root\scripts\minitab_cli.py" --db "$root\runtime\knowledge\experience.db" `
       --out "$root\runtime\outputs" run "对 C1 做过程能力分析 LSL=9 USL=17" --backend com --data
```
