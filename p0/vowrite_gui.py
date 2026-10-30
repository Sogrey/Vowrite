#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vowrite GUI — 托盘常驻、右键菜单设置、llama-server 一键管理。

用法：
  pythonw p0\vowrite_gui.py    # 推荐：无窗口常驻托盘（start_vowrite.bat 即此）
  python p0\vowrite_gui.py     # 带控制台调试
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import pystray
import tomlkit
from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import vowrite  # noqa: E402
from vowrite import (  # noqa: E402
    Vowrite,
    __version__,
    load_config,
    log,
    self_test,
    set_log_file,
)

PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "config.toml"
TEMP_DIR = PROJECT_ROOT / ".temp"
LOG_PATH = TEMP_DIR / "vowrite-gui.log"
LOCK_PATH = TEMP_DIR / "vowrite-gui.lock"
SERVER_LOG = TEMP_DIR / "llama-server.log"

# 托盘图标状态色
C_IDLE = (96, 96, 96, 255)
C_RECORDING = (214, 60, 60, 255)
C_PROCESSING = (56, 118, 214, 255)
C_LOADING = (222, 170, 40, 255)
C_ERROR = (140, 20, 20, 255)


def _make_icon(color) -> Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=color)
    d.ellipse((26, 26, 38, 38), fill=(255, 255, 255, 255))
    return img


# --------------------------------------------------------------------------
# 单实例锁（ctypes OpenProcess 探测，零额外依赖）
# --------------------------------------------------------------------------


def acquire_lock() -> bool:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text().strip())
            k32 = ctypes.windll.kernel32
            handle = k32.OpenProcess(0x00100000, False, old_pid)  # SYNCHRONIZE
            if handle:
                k32.CloseHandle(handle)
                return False  # 已有存活实例
        except Exception:  # noqa: BLE001 — 锁文件损坏则视为无实例
            pass
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# llama-server 托管（只管自己拉起的进程；外部已运行的服务只报状态）
# --------------------------------------------------------------------------


class LlmServerManager:
    def __init__(self, llm_cfg: dict) -> None:
        self._lock = threading.Lock()
        self._cfg: dict = llm_cfg.get("server", {}) or {}
        self._proc: subprocess.Popen | None = None

    def refresh_cfg(self, llm_cfg: dict) -> None:
        with self._lock:
            self._cfg = llm_cfg.get("server", {}) or {}

    @property
    def host(self) -> str:
        return str(self._cfg.get("host", "127.0.0.1"))

    @property
    def port(self) -> int:
        return int(self._cfg.get("port", 8090))

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("enabled", False))

    @property
    def auto_start(self) -> bool:
        return bool(self._cfg.get("auto_start", False))

    def health_ok(self) -> bool:
        try:
            import requests

            r = requests.get(f"http://{self.host}:{self.port}/health", timeout=2)
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    @property
    def is_owned(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def status_text(self) -> str:
        if self.is_owned:
            return f"运行中（托管 · 端口 {self.port}）"
        if self.health_ok():
            return f"运行中（外部进程 · 端口 {self.port}）"
        return "已停止"

    def start(self, timeout: float = 90) -> tuple:
        if self.is_owned:
            return True, "托管进程已在运行"
        if self.health_ok():
            return True, "端口上已有服务在运行（外部进程，不托管）"
        exe = str(self._cfg.get("exe", ""))
        model = str(self._cfg.get("model", ""))
        if not exe or not Path(exe).exists():
            return False, "llama-server 路径未配置或不存在，请打开设置填写"
        if not model or not Path(model).exists():
            return False, "GGUF 模型路径未配置或不存在，请打开设置填写"

        args = [exe, "-m", model, "--host", self.host, "--port", str(self.port)]
        extra = str(self._cfg.get("args", "")).strip()
        if extra:
            args += extra.split()
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(SERVER_LOG, "ab") as lf:
                proc = subprocess.Popen(
                    args, stdout=lf, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:  # noqa: BLE001
            return False, f"启动失败: {e}"
        with self._lock:
            self._proc = proc
        log("SRV", f"llama-server 已拉起 (pid={proc.pid}, port={self.port})，等待就绪…")
        t0 = time.time()
        while time.time() - t0 < timeout:
            if proc.poll() is not None:
                with self._lock:
                    self._proc = None
                return False, f"llama-server 启动后退出，日志: {SERVER_LOG}"
            if self.health_ok():
                log("SRV", "llama-server 就绪")
                return True, "llama-server 已启动并就绪"
            time.sleep(1)
        return False, "等待 llama-server 就绪超时（模型加载慢可重试）"

    def stop(self) -> str:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return "无托管进程（外部服务不受影响）"
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            proc.kill()
        log("SRV", "已停止托管的 llama-server")
        return "已停止托管进程"


# --------------------------------------------------------------------------
# 设置窗（配置驱动生成控件；tomlkit 保留注释写回）
# --------------------------------------------------------------------------

FIELDS = [
    ("触发与监听", [
        ("trigger.key", "触发键（按住说话）", "text", None),
    ]),
    ("输出模式", [
        ("llm.mode", "模式", "choice", ["polish", "chat", "raw"]),
        ("llm.style", "润色强度", "choice", ["light", "heavy"]),
    ]),
    ("ASR 语音识别", [
        ("asr.model", "模型（HF 名称或本地路径）", "text", None),
        ("asr.device", "设备", "choice", ["auto", "cpu", "cuda"]),
        ("asr.compute_type", "计算精度", "choice", ["auto", "int8", "float16"]),
        ("asr.language", "语音语言", "choice", ["zh", "en", "auto"]),
        ("asr.hallucination_fingerprints", "幻觉短语黑名单（逗号分隔，遇新幻觉自行追加）", "csv", None),
    ]),
    ("LLM 处理", [
        ("llm.base_url", "接口地址", "text", None),
        ("llm.model", "模型名", "text", None),
        ("llm.timeout", "超时（秒）", "int", None),
    ]),
    ("LLM 服务托管（llama-server）", [
        ("llm.server.enabled", "启用托管功能", "bool", None),
        ("llm.server.auto_start", "随 Vowrite 自动启动", "bool", None),
        ("llm.server.exe", "llama-server.exe 路径", "text", None),
        ("llm.server.model", "GGUF 模型路径", "text", None),
        ("llm.server.args", "附加启动参数", "text", None),
        ("llm.server.port", "端口", "int", None),
    ]),
    ("注入", [
        ("inject.enabled", "自动粘贴到光标", "bool", None),
        ("inject.pause_ms", "粘贴前等待（ms）", "int", None),
    ]),
]


def _get_nested(d: dict, dotted: str, default=None):
    cur = d
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _set_nested(d, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for k in parts[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = tomlkit.table()
        cur = cur[k]
    cur[parts[-1]] = value


# --------------------------------------------------------------------------
# 主应用
# --------------------------------------------------------------------------


class VowriteGui:
    def __init__(self) -> None:
        self.cfg = load_config(CONFIG_PATH)
        set_log_file(LOG_PATH)
        log("GUI", f"Vowrite GUI v{__version__} 启动 (pid={os.getpid()})")

        self.engine: Vowrite | None = None
        self.engine_error = ""
        self.monitoring = False

        self.server = LlmServerManager(self.cfg["llm"])

        self.root = tk.Tk()
        self.root.withdraw()
        self._init_style()

        self._vars: dict = {}
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None

        self.icon = pystray.Icon(
            "Vowrite", _make_icon(C_LOADING),
            "Vowrite：引擎加载中…", self._build_menu())
        threading.Thread(target=self._startup_flow, daemon=True).start()
        threading.Thread(target=self._ui_refresher, daemon=True).start()
        self.icon.run_detached()
        self.root.mainloop()

    # -- 样式 ---------------------------------------------------------------

    def _init_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass
        self.root.option_add("*Font", ("Microsoft YaHei UI", 9))

    # -- 启动流程（后台线程） -----------------------------------------------

    def _startup_flow(self) -> None:
        # 1) llama-server：配置了托管且自动启动 → 拉起（外部已跑则跳过）
        try:
            if self.server.enabled and self.server.auto_start and not self.server.health_ok():
                ok, msg = self.server.start()
                log("SRV", f"自动启动: {msg}")
                if not ok:
                    self.icon.notify(f"llama-server 自动启动失败：{msg}", "Vowrite")
        except Exception as e:  # noqa: BLE001
            log("SRV", f"自动启动异常: {e}")
        # 2) ASR 引擎加载（首次 ~30s）
        self._reload_engine()

    def _reload_engine(self) -> None:
        was_running = self.engine is not None
        self._engine_stop()
        try:
            cfg = load_config(CONFIG_PATH)  # 每次重建都读最新配置
            self.cfg = cfg
            self.server.refresh_cfg(cfg["llm"])
            engine = Vowrite(cfg)
            engine.start()
            self.engine = engine
            self.monitoring = True
            self.engine_error = ""
            log("GUI", "引擎就绪，监听已开启")
        except Exception as e:  # noqa: BLE001
            self.engine = None
            self.monitoring = False
            self.engine_error = str(e)
            log("ERR", f"引擎加载失败: {e}")
            self.icon.notify(f"引擎加载失败：{e}", "Vowrite")
        if was_running:
            self.icon.update_menu()

    def _engine_stop(self) -> None:
        if self.engine is not None:
            try:
                self.engine.stop()
            except Exception:  # noqa: BLE001
                pass
            self.engine = None

    # -- 托盘 ----------------------------------------------------------------

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(lambda _: self._toggle_monitor_text(),
                             self._on_toggle_monitor, default=True),
            pystray.MenuItem(lambda _: self._mode_text(), self._on_toggle_mode),
            pystray.MenuItem(lambda _: f"LLM 服务：{self.server.status_text()}（点击启停）",
                             self._on_toggle_server),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开设置…", self._on_open_settings),
            pystray.MenuItem("重启引擎（换模型/设备后用）", self._on_restart_engine),
            pystray.MenuItem("重启 GUI（更新代码后用）", self._on_restart_gui),
            pystray.MenuItem("运行自检", self._on_selftest),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_quit),
        )

    def _toggle_monitor_text(self) -> str:
        if self.engine is None:
            return f"引擎：未加载{f'（{self.engine_error[:30]}…）' if self.engine_error else ''}"
        return f"监听：{'开启中' if self.monitoring else '已暂停'}（点击切换）"

    def _mode_text(self) -> str:
        mode = self.engine.polisher.mode if self.engine else \
            self.cfg["llm"].get("mode", "polish")
        desc = {"polish": "polish · 转写润色（替代打字）",
                "chat": "chat · 口述问答（答案落光标）",
                "raw": "raw · 纯转写（LLM 不参与）"}
        return f"模式：{desc.get(mode, mode)}（点击切换）"

    def _on_toggle_mode(self, *_):
        if self.engine is None:
            return
        # 三态循环：polish → chat → raw → polish
        order = ["polish", "chat", "raw"]
        cur = self.engine.polisher.mode
        new = order[(order.index(cur) + 1) % len(order)] if cur in order else "polish"
        self.engine.polisher.mode = new
        self.cfg["llm"]["mode"] = new  # 供下次重启沿用（内存态，不改文件）
        log("GUI", f"模式切换为 {new}")
        self.icon.notify(f"输出模式：{new}", "Vowrite")
        self.icon.update_menu()

    def _on_toggle_monitor(self, *_):
        if self.engine is None:
            self.icon.notify("引擎未就绪，无法切换监听", "Vowrite")
            return
        if self.monitoring:
            self.engine.stop()
            self.monitoring = False
            log("GUI", "监听已暂停")
        else:
            self.engine.start()
            self.monitoring = True
            log("GUI", "监听已恢复")
        self.icon.update_menu()

    def _on_toggle_server(self, *_):
        def worker():
            if self.server.is_owned:
                msg = self.server.stop()
            elif self.server.health_ok():
                msg = "服务是外部进程，Vowrite 不代管，请手动处理"
            else:
                ok, msg = self.server.start()
                if not ok:
                    self.icon.notify(msg, "Vowrite")
                    return
            self.icon.notify(msg, "Vowrite")
            self.icon.update_menu()
        threading.Thread(target=worker, daemon=True).start()

    def _on_open_settings(self, *_):
        self.root.after(0, self._show_settings)

    def _on_restart_engine(self, *_):
        threading.Thread(target=self._reload_engine, daemon=True).start()

    def _on_restart_gui(self, *_):
        """退出当前实例后自动拉起新实例（非 daemon 线程保证延迟启动被执行）。"""
        bat = str(SCRIPT_DIR / "start_vowrite.bat")
        if not Path(bat).exists():
            self.icon.notify("找不到 start_vowrite.bat，请手动退出后双击启动", "Vowrite")
            return

        def worker():
            time.sleep(0.8)  # 等旧实例退出、锁释放后再拉起新实例
            try:
                os.startfile(bat)
            except Exception as e:  # noqa: BLE001
                log("GUI", f"重启拉起失败: {e}")

        threading.Thread(target=worker).start()  # 非 daemon：进程退出前会执行完
        self._on_quit()

    def _on_selftest(self, *_):
        def worker():
            ok = self.run_selftest()
            self.icon.notify("自检完成：全部通过" if ok else "自检有失败项，详见日志",
                             "Vowrite")
        threading.Thread(target=worker, daemon=True).start()

    def run_selftest(self) -> bool:
        try:
            return self_test(self.cfg, full=False, inject_enabled=True)
        except Exception as e:  # noqa: BLE001
            log("ERR", f"自检异常: {e}")
            return False

    def _on_quit(self, *_):
        log("GUI", "退出")
        self._engine_stop()
        if self.server.is_owned:
            self.server.stop()
        release_lock()
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001
            pass
        self.root.after(0, self.root.destroy)

    # -- 状态刷新线程 ---------------------------------------------------------

    def _ui_refresher(self) -> None:
        icon_cache: dict = {}
        while True:
            color, tip = C_IDLE, "Vowrite：待机"
            if self.engine is None:
                color, tip = (C_ERROR if self.engine_error else C_LOADING), \
                    ("Vowrite：引擎加载失败，右键查看菜单" if self.engine_error
                     else "Vowrite：引擎加载中…")
            else:
                state = self.engine.state
                if state == vowrite.STATE_RECORDING:
                    color, tip = C_RECORDING, "Vowrite：录音中…"
                elif state == vowrite.STATE_PROCESSING:
                    color, tip = C_PROCESSING, "Vowrite：处理中…"
                elif not self.monitoring:
                    color, tip = C_IDLE, "Vowrite：监听已暂停"
            if icon_cache.get("color") != color:
                icon_cache["color"] = color
                try:
                    self.icon.icon = _make_icon(color)
                except Exception:  # noqa: BLE001
                    pass
            if icon_cache.get("tip") != tip:
                icon_cache["tip"] = tip
                try:
                    self.icon.title = tip
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.4)

    # -- 设置窗 ---------------------------------------------------------------

    def _show_settings(self) -> None:
        if self._win is None:
            self._win = self._build_settings_window()
        else:
            self._sync_vars_from_cfg()
        if self._canvas is not None:
            self._canvas.yview_moveto(0)  # 每次打开回到顶部
        self._win.deiconify()
        self._win.lift()
        self._win.focus_force()

    def _build_settings_window(self) -> tk.Toplevel:
        win = tk.Toplevel(self.root)
        win.title("Vowrite 设置")
        win.geometry("560x640")
        win.protocol("WM_DELETE_WINDOW", win.withdraw)

        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)

        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=4)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        # 宽度自适应：inner 跟随 canvas 宽度，避免内容横向溢出
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(_win_id, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._canvas = canvas

        # 鼠标滚轮（Windows <MouseWheel>）：bind_all 保证悬停在任意子控件上也能滚动；
        # delta=120/格，每格滚动 40 像素（canvas units 默认 1px）
        def _on_wheel(event):
            if win.winfo_viewable():
                canvas.yview_scroll(int(-event.delta / 120) * 40, "units")

        win.bind_all("<MouseWheel>", _on_wheel)

        self._vars = {}
        for section, fields in FIELDS:
            box = ttk.LabelFrame(inner, text=section, padding=10)
            box.pack(fill="x", pady=6)
            for dotted, label, kind, choices in fields:
                row = ttk.Frame(box)
                row.pack(fill="x", pady=3)
                ttk.Label(row, text=label, width=24, anchor="e").pack(side="left")
                value = _get_nested(self.cfg, dotted, "")
                if kind == "csv":
                    value = ", ".join(value) if isinstance(value, list) else str(value)
                var = (tk.BooleanVar(value=bool(value)) if kind == "bool"
                       else tk.StringVar(value=str(value)))
                if kind == "bool":
                    ttk.Checkbutton(row, variable=var).pack(side="left")
                elif kind == "choice":
                    ttk.Combobox(row, textvariable=var, values=choices,
                                 state="readonly", width=32).pack(side="left")
                elif kind == "int":
                    ttk.Spinbox(row, textvariable=var, from_=0, to=99999,
                                width=10).pack(side="left")
                else:
                    ttk.Entry(row, textvariable=var, width=42).pack(side="left")
                self._vars[dotted] = (var, kind)

        buttons = ttk.Frame(inner)
        buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="保存", command=self._on_save).pack(side="left", padx=4)
        ttk.Button(buttons, text="保存并重启引擎",
                   command=self._on_save_restart).pack(side="left", padx=4)
        ttk.Button(buttons, text="关闭", command=win.withdraw).pack(side="right", padx=4)

        self._autostart_var = tk.BooleanVar(value=self._autostart_enabled())
        ttk.Checkbutton(
            inner, text="开机自动启动 Vowrite（当前用户注册表 Run）",
            variable=self._autostart_var,
            command=self._on_toggle_autostart).pack(anchor="w", pady=6)
        return win

    def _sync_vars_from_cfg(self) -> None:
        self.cfg = load_config(CONFIG_PATH)
        for dotted, (var, kind) in self._vars.items():
            value = _get_nested(self.cfg, dotted, "")
            if kind == "csv":
                value = ", ".join(value) if isinstance(value, list) else str(value)
            var.set(bool(value) if kind == "bool" else str(value))
        self._autostart_var.set(self._autostart_enabled())

    def _on_save(self) -> None:
        try:
            doc = tomlkit.parse(CONFIG_PATH.read_text(encoding="utf-8"))
            for dotted, (var, kind) in self._vars.items():
                raw = var.get()
                if kind == "bool":
                    value = bool(raw)
                elif kind == "int":
                    value = int(str(raw).strip() or 0)
                elif kind == "csv":
                    value = [x.strip() for x in str(raw).split(",") if x.strip()]
                else:
                    value = str(raw).strip()
                _set_nested(doc, dotted, value)
            CONFIG_PATH.write_text(tomlkit.dumps(doc), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Vowrite", f"保存失败：{e}")
            return
        # 重读配置并热更新运行时项
        self.cfg = load_config(CONFIG_PATH)
        self.server.refresh_cfg(self.cfg["llm"])
        if self.engine is not None:
            self.engine.cfg = self.cfg
            self.engine.apply_runtime_config()
            # 幻觉黑名单属 ASR 段：热更新到引擎实例，无需重启
            if self.engine.transcriber is not None:
                extra = self.cfg["asr"].get("hallucination_fingerprints") or []
                fp = tuple(vowrite.HALLUCINATION_FINGERPRINTS) + tuple(
                    str(x).strip().lower() for x in extra if str(x).strip())
                self.engine.transcriber.fingerprints = fp
        self.icon.update_menu()
        messagebox.showinfo(
            "Vowrite",
            "已保存。触发键/模式/润色强度/注入等已热生效；\n"
            "ASR 模型与设备变更需点「保存并重启引擎」。")

    def _on_save_restart(self) -> None:
        self._on_save_quiet()
        threading.Thread(target=self._reload_engine, daemon=True).start()
        if self._win:
            self._win.withdraw()

    def _on_save_quiet(self) -> None:
        # 供「保存并重启引擎」复用：保存逻辑同 _on_save，但抑制弹窗
        try:
            doc = tomlkit.parse(CONFIG_PATH.read_text(encoding="utf-8"))
            for dotted, (var, kind) in self._vars.items():
                raw = var.get()
                if kind == "bool":
                    value = bool(raw)
                elif kind == "int":
                    value = int(str(raw).strip() or 0)
                elif kind == "csv":
                    value = [x.strip() for x in str(raw).split(",") if x.strip()]
                else:
                    value = str(raw).strip()
                _set_nested(doc, dotted, value)
            CONFIG_PATH.write_text(tomlkit.dumps(doc), encoding="utf-8")
            self.cfg = load_config(CONFIG_PATH)
            self.server.refresh_cfg(self.cfg["llm"])
        except Exception as e:  # noqa: BLE001
            log("ERR", f"保存失败: {e}")

    # -- 开机自启（HKCU Run，用户级，可随时取消） ------------------------------

    _RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _RUN_NAME = "Vowrite"

    @staticmethod
    def _autostart_command() -> str:
        bat = PROJECT_ROOT / "start_vowrite.bat"
        return f'"{bat}"' if bat.exists() else \
            f'"{PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"}" "{SCRIPT_DIR / "vowrite_gui.py"}"'

    def _autostart_enabled(self) -> bool:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._RUN_KEY) as k:
                winreg.QueryValueEx(k, self._RUN_NAME)
                return True
        except OSError:
            return False
        except Exception:  # noqa: BLE001
            return False

    def _on_toggle_autostart(self) -> None:
        import winreg

        try:
            if self._autostart_var.get():
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._RUN_KEY,
                                    0, winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, self._RUN_NAME, 0, winreg.REG_SZ,
                                      self._autostart_command())
                log("GUI", "已写入开机自启（HKCU Run）")
            else:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._RUN_KEY,
                                        0, winreg.KEY_SET_VALUE) as k:
                        winreg.DeleteValue(k, self._RUN_NAME)
                except OSError:
                    pass
                log("GUI", "已移除开机自启")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Vowrite", f"注册表操作失败：{e}")
            self._autostart_var.set(self._autostart_enabled())


def main() -> int:
    if not acquire_lock():
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("Vowrite", "Vowrite 已在运行（托盘可找），本窗口退出。")
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
        return 0
    crash_log = TEMP_DIR / "vowrite-gui-crash.log"
    try:
        VowriteGui()
    except Exception:  # noqa: BLE001 — pythonw 无 stderr，崩溃必须落盘可查
        import traceback

        try:
            crash_log.parent.mkdir(parents=True, exist_ok=True)
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S] GUI 崩溃:\n")
                        + traceback.format_exc() + "\n")
        except Exception:  # noqa: BLE001
            pass
        return 1
    finally:
        release_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
