<div align="center">

# Vowrite（述写）

> **Speak to Write**

**按住快捷键口述，AI 实时转写并润色，文字直接输出到当前光标位置，无需切换窗口。**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)]()
[![Stage](https://img.shields.io/badge/stage-P0%20prototype-orange)]()
[![Platform](https://img.shields.io/badge/platform-Windows-blue)]()

</div>

---

Vowrite 是一款全局语音输入工具。按住快捷键口述，AI 将你的语音实时转为文字并自动润色，文字直接输出到当前光标位置，无需切换窗口。解放双手，让口述即书写。

> Vowrite is a global voice input tool. Hold the hotkey and speak, AI transcribes and polishes your speech in real time, text lands directly at your cursor anywhere. Speak to write.

## 工作原理

```
按住右Ctrl ──► 录音 16kHz ──► ASR 转写 ──► LLM 润色 ──► 剪贴板+模拟粘贴 ──► 光标处
 (keyboard)     (sounddevice)  (faster-whisper   (OpenAI 兼容接口,     (pyperclip +
                               / 云端 API 可选)    失败自动降级原转写)   pyautogui)
```

- **触发**：按住 `右Ctrl` 开口说话，松开即完成
- **转写**：本地 faster-whisper（CUDA 优先，自动回退 CPU），或切换任意 OpenAI 兼容转写 API
- **润色**：两档强度——`light` 只清口水词/标点/错字、忠实原意；`heavy` 可书面化改写
- **注入**：写入剪贴板 + 模拟 `Ctrl+V`，任何应用的输入框都能落位

## 快速开始

```powershell
# 1) 克隆并进入项目
cd D:\workspace\sogrey\Vowrite

# 2) 创建虚拟环境（Python 3.12+）
python -m venv .venv

# 3) 安装依赖（国内推荐清华源）
.venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4) 轻量自检（依赖/配置/麦克风/剪贴板/LLM）
.venv\Scripts\python.exe p0\vowrite.py --self-test

# 5) 完整自检（首次会下载 ASR 模型，约 460MB，走 hf-mirror）
.venv\Scripts\python.exe p0\vowrite.py --self-test --full

# 6) 启动常驻监听
.venv\Scripts\python.exe p0\vowrite.py
```

启动后：**按住右 Ctrl 说话 → 松开 → 文字自动落在光标处**。`Ctrl+C` 退出。

> LLM 润色默认指向本地 llama.cpp server（`http://127.0.0.1:8090/v1`），先启动它效果最佳：
> ```
> llama-server.exe -m Qwen2.5-7B-Instruct-Q4_K_M.gguf -ngl 99 --port 8090
> ```
> 没启动也不影响使用——润色会自动降级为输出原始转写。也可在 `config.toml` 指向云端 API（DeepSeek / Qwen 等）。

## 常用命令

| 命令 | 用途 |
|---|---|
| `python p0\vowrite.py` | 常驻监听（主用法） |
| `python p0\vowrite.py --message "嗯那个我在想等下要不要吃饭"` | 跳过录音，直接测润色+注入 |
| `python p0\vowrite.py --no-inject` | 只打印/写剪贴板，不模拟粘贴（安全模式） |
| `python p0\vowrite.py --style heavy` | 临时用书面化强度润色 |
| `python p0\vowrite.py --self-test [--full]` | 自检 / 完整链路自检 |

## 配置

首次运行会自动把 `config.example.toml` 复制为 `config.toml`，按需修改：

| 配置段 | 关键项 | 说明 |
|---|---|---|
| `[trigger]` | `key` | 触发键（keyboard 库按键名）：`right ctrl` / `f9` / `right shift`… |
| `[audio]` | `min_duration` / `max_duration` | 误触过滤 / 最长录音保护（秒） |
| `[asr]` | `engine` | `local`（faster-whisper）或 `api`（OpenAI 兼容转写） |
| | `model` | `tiny` / `base` / `small` / `medium` / `large-v3-turbo` |
| | `device` | `auto`（CUDA→CPU 回退）/ `cuda` / `cpu` |
| | `hf_endpoint` | 模型下载镜像，默认 `https://hf-mirror.com`（国内网络） |
| `[llm]` | `base_url` / `model` / `style` | OpenAI 兼容接口；`style` 为 `light` / `heavy` |
| `[inject]` | `enabled` / `pause_ms` | 注入开关；写剪贴板→粘贴的间隔 |

## 已知边界

- **GPU 加速**：`device=auto` 先试 CUDA，缺 CUDA 运行库时自动回退 CPU int8（首次自检会打印实际生效配置）；模型质量不够时换 `medium` / `large-v3-turbo`
- **管理员窗口**：向以管理员权限运行的应用注入时，需 Vowrite 同样以管理员启动（Windows UIPI 限制）
- **杀软误报**：全局键盘钩子（keyboard 库）可能被安全软件关注，属正常行为
- **剪贴板**：注入会覆盖当前剪贴板内容

## 路线图

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | Python CLI 原型（本目录） | 🚧 进行中 |
| P1 | Tauri 2 桌面版：悬浮指示器 / 历史 / 设置 | 待启动 |
| P2 | 双引擎回退 / 个人词库 / 修正学习 | 待启动 |
| P3 | 流式实时预览 / 选中改写 | 待启动 |

完整需求见 [docs/PRD.md](docs/PRD.md)。

## 声明

- 个人学习项目：以 [Typeoff](https://typeoff.ai) 为公开对标对象的独立实现，不使用其任何代码、素材与文案
- 所有核心组件均为公开开源技术（faster-whisper / sounddevice / keyboard / pyautogui 等）

> AI生成
