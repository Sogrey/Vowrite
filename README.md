<div align="center">

# Vowrite（述写）

> \*\*Speak to Write\*\*

**按住快捷键口述，AI 实时转写并润色，文字直接输出到当前光标位置，无需切换窗口。**

\[!\[Python](https://img.shields.io/badge/python-3.12%2B-blue)]()
\[!\[Stage](https://img.shields.io/badge/stage-P0%20prototype-orange)]()
\[!\[Platform](https://img.shields.io/badge/platform-Windows-blue)]()

</div>

\---

Vowrite 是一款全局语音输入工具。按住快捷键口述，AI 将你的语音实时转为文字并自动润色，文字直接输出到当前光标位置，无需切换窗口。解放双手，让口述即书写。

> Vowrite is a global voice input tool. Hold the hotkey and speak, AI transcribes and polishes your speech in real time, text lands directly at your cursor anywhere. Speak to write.

## 工作原理

```
按住右Ctrl ──► 录音 16kHz ──► ASR 转写 ──► LLM 处理 ──► 剪贴板+模拟粘贴 ──► 光标处
 (keyboard)     (sounddevice)  (faster-whisper   (polish=转写润色/       (pyperclip +
                                / 云端 API 可选)    chat=口述问答,        pyautogui)
                                                   失败降级原文本)
```

### 两种输出模式（`--mode` 或 `config.toml [llm] mode` 切换）

| 模式 | 做什么 | 适用场景 |
|---|---|---|
| `polish`（默认） | **把你说的话打成干净文字**：只清口水词/补标点/纠错字，原意原句保留 | 替代打字：对 Cursor/Claude Code 口述 prompt、写 commit message、博客周报 |
| `chat` | 口述一个问题，**AI 答案直接落光标** | 文档里随口问知识、快速取代码片段 |

* **触发**：按住 `右Ctrl` 开口说话，松开即完成
* **转写**：本地 faster-whisper（CUDA 优先，自动回退 CPU），或切换任意 OpenAI 兼容转写 API
* **注入**：写入剪贴板 + 模拟 `Ctrl+V`，任何应用的输入框都能落位

## 快速开始

```powershell
# 1) 克隆并进入项目
cd D:\\workspace\\sogrey\\Vowrite

# 2) 创建虚拟环境（Python 3.12+）
python -m venv .venv

# 3) 安装依赖（国内推荐清华源）
.venv\\Scripts\\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4) 轻量自检（依赖/配置/麦克风/剪贴板/LLM）
.venv\\Scripts\\python.exe p0\\vowrite.py --self-test

# 5) 完整自检（首次会下载 ASR 模型，约 460MB，走 hf-mirror）
.venv\\Scripts\\python.exe p0\\vowrite.py --self-test --full

# 6) 启动常驻监听
.venv\\Scripts\\python.exe p0\\vowrite.py
```

启动后：**按住右 Ctrl 说话 → 松开 → 文字自动落在光标处**。`Ctrl+C` 退出。

> LLM 处理默认指向本地 llama.cpp server（`http://127.0.0.1:8090/v1`），先启动它效果最佳：
> ```
> llama-server.exe -m Qwen2.5-7B-Instruct-Q4\_K\_M.gguf -ngl 99 --port 8090
> ```
> 没启动也不影响使用——处理会自动降级为输出原始转写。也可在 `config.toml` 指向云端 API（DeepSeek / Qwen 等）。
>
> 模型建议：polish 转写清理需要严格的指令遵循，推荐 **instruct 指令模型**（如官方 Qwen2.5-7B-Instruct）；角色扮演/对话微调模型可能不守规则、把转写内容当对话来回答。

## 常用命令

|命令|用途|
|-|-|
|`python p0\vowrite.py`|常驻监听（主用法，polish 模式替代打字）|
|`python p0\vowrite.py --mode chat`|问答模式：说问题，AI 答案落光标|
|`python p0\vowrite.py --message "嗯那个我在想等下要不要吃饭"`|跳过录音，直接测润色+注入|
|`python p0\vowrite.py --no-inject`|只打印/写剪贴板，不模拟粘贴（安全模式）|
|`python p0\vowrite.py --style heavy`|临时用书面化强度润色|
|`python p0\vowrite.py --self-test \[--full]`|自检 / 完整链路自检|

## 配置

首次运行会自动把 `config.example.toml` 复制为 `config.toml`，按需修改：

|配置段|关键项|说明|
|-|-|-|
|`\[trigger]`|`key`|触发键（keyboard 库按键名）：`right ctrl` / `f9` / `right shift`…|
|`\[audio]`|`min\_duration` / `max\_duration`|误触过滤 / 最长录音保护（秒）|
|`\[asr]`|`engine`|`local`（faster-whisper）或 `api`（OpenAI 兼容转写）|
||`model`|`tiny` / `base` / `small` / `medium` / `large-v3-turbo`|
||`device`|`auto`（CUDA→CPU 回退）/ `cuda` / `cpu`|
||`hf\_endpoint`|模型下载镜像，默认 `https://hf-mirror.com`（国内网络）|
|`\[llm]`|`mode`|输出模式：`polish`（转写润色，默认）/ `chat`（口述问答落光标）|
||`base\_url` / `model` / `style`|OpenAI 兼容接口；`style` 为 `light` / `heavy`|
|`\[inject]`|`enabled` / `pause\_ms`|注入开关；写剪贴板→粘贴的间隔|

## 已知边界

* **GPU 加速**：`device=auto` 先试 CUDA（构造后用合成音预热验证，构造成功≠能推理），失败自动回退 CPU int8；Windows 若报 `cublas64_12.dll is not found`，把本机 CUDA 12 运行库目录填入 `config.toml` 的 `cuda_dll_dirs`（如 PyTorch 自带的 `...\torch\lib`）
* **管理员窗口**：向以管理员权限运行的应用注入时，需 Vowrite 同样以管理员启动（Windows UIPI 限制）
* **杀软误报**：全局键盘钩子（keyboard 库）可能被安全软件关注，属正常行为
* **剪贴板**：注入会覆盖当前剪贴板内容

## 路线图

|阶段|内容|状态|
|-|-|-|
|P0|Python CLI 原型（本目录）|🚧 进行中|
|P1|Tauri 2 桌面版：悬浮指示器 / 历史 / 设置|待启动|
|P2|双引擎回退 / 个人词库 / 修正学习|待启动|
|P3|流式实时预览 / 选中改写|待启动|

完整需求见 [docs/PRD.md](docs/PRD.md)。

> AI生成
