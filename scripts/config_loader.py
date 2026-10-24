#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载器：统一从 config.ini 读取配置，勿在命令行传 Key。

优先级：环境变量 > config.ini
环境变量仅用于 CI 等自动化场景，本地开发请直接改config.ini。
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent   # 技能根目录
CONFIG_PATH = BASE_DIR / "config.ini"

_DEFAULTS = {
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
    },
    "experiment": {
        "run_with_wavelength": "true",
        "temperature": "0.0",
        "max_tokens": "800",
        "retries": "3",
        "timeout": "60",
        "request_interval": "0.3",
    },
    "platform": {
        "base_url": "https://openge.org.cn/api",
        "request_interval": "0.03",
        "username": "",
        "password": "",
        "access_token": "",
        "retries": "3",
        "timeout": "30",
    },
    "jev": {
        "base_url": "https://inference.do-ai.run/v1/systemone",
        "api_key": "",
        "model": "typesafe-jev-1.13.0",
        "timeout": "30",
        "retries": "3",
        "request_interval": "0.2",
        "conf_high": "0.80",
        "conf_low": "0.60",
        "with_wavelength": "true",
    },
    "rag": {
        "ollama_base_url": "",
        "ollama_embedding_model": "",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "top_k": "3",
        "max_candidates": "40",
    },
    "output": {
        "excel_name": "算子波段匹配矩阵.xlsx",
        "llm_result_prefix": "llm_results",
    },
}


class Config:
    """全局配置单例。"""

    def __init__(self, path: Path | None = None):
        self.path = path or CONFIG_PATH
        self._cp = configparser.ConfigParser()
        # 先灌默认值，保证缺项不崩
        for sec, kv in _DEFAULTS.items():
            self._cp[sec] = kv
        if self.path.exists():
            self._cp.read(self.path, encoding="utf-8")
        else:
            raise FileNotFoundError(
                f"找不到配置文件 {self.path}\n"
                f"请复制 config.example.ini 为 config.ini 并填入实际值。")

    # ---------------- 读取 ----------------
    def get(self, section: str, key: str) -> str:
        env_key = f"OGE_{section.upper()}_{key.upper()}"
        return os.getenv(env_key) or self._cp.get(section, key)

    def get_float(self, section: str, key: str) -> float:
        return float(self.get(section, key))

    def get_int(self, section: str, key: str) -> int:
        return int(self.get(section, key))

    def get_bool(self, section: str, key: str) -> bool:
        return self.get(section, key).strip().lower() in ("1", "true", "yes", "y", "on")

    # ---------------- 快捷属性 ----------------
    @property
    def llm_base_url(self) -> str:
        return self.get("llm", "base_url").rstrip("/")

    @property
    def llm_api_key(self) -> str:
        return self.get("llm", "api_key").strip()

    @property
    def llm_model(self) -> str:
        return self.get("llm", "model").strip()

    @property
    def run_with_wavelength(self) -> bool:
        return self.get_bool("experiment", "run_with_wavelength")

    @property
    def temperature(self) -> float:
        return self.get_float("experiment", "temperature")

    @property
    def max_tokens(self) -> int:
        return self.get_int("experiment", "max_tokens")

    @property
    def retries(self) -> int:
        return self.get_int("experiment", "retries")

    @property
    def timeout(self) -> int:
        return self.get_int("experiment", "timeout")

    @property
    def llm_interval(self) -> float:
        return self.get_float("experiment", "request_interval")

    @property
    def platform_base_url(self) -> str:
        return self.get("platform", "base_url").rstrip("/")

    @property
    def platform_interval(self) -> float:
        return self.get_float("platform", "request_interval")

    @property
    def oge_username(self) -> str:
        return self.get("platform", "username").strip()

    @property
    def oge_password(self) -> str:
        return self.get("platform", "password").strip()

    @property
    def oge_token(self) -> str:
        return self.get("platform", "access_token").strip()

    @property
    def platform_retries(self) -> int:
        return self.get_int("platform", "retries")

    @property
    def platform_timeout(self) -> int:
        return self.get_int("platform", "timeout")

    def platform_headers(self) -> dict:
        """
        构造 OGE 请求头。

        实测公开接口免鉴权，故凭据可为空；填了则自动带上，
        用于访问私有算子或提高频率配额。
        """
        h = {"Content-Type": "application/json"}
        if self.oge_token:
            h["Authorization"] = f"Bearer {self.oge_token}"
        return h

    def has_credentials(self) -> bool:
        return bool(self.oge_token or (self.oge_username and self.oge_password))

    @property
    def excel_name(self) -> str:
        return self.get("output", "excel_name")

    @property
    def llm_result_prefix(self) -> str:
        return self.get("output", "llm_result_prefix")

    # ---------------- Jev ----------------
    @property
    def jev_base_url(self) -> str:
        return self.get("jev", "base_url").rstrip("/")

    @property
    def jev_api_key(self) -> str:
        return self.get("jev", "api_key").strip()

    @property
    def jev_model(self) -> str:
        return self.get("jev", "model").strip()

    @property
    def jev_timeout(self) -> int:
        return self.get_int("jev", "timeout")

    @property
    def jev_retries(self) -> int:
        return self.get_int("jev", "retries")

    @property
    def jev_interval(self) -> float:
        return self.get_float("jev", "request_interval")

    @property
    def conf_high(self) -> float:
        return self.get_float("jev", "conf_high")

    @property
    def conf_low(self) -> float:
        return self.get_float("jev", "conf_low")

    @property
    def jev_with_wavelength(self) -> bool:
        return self.get_bool("jev", "with_wavelength")

    def validate_jev(self) -> None:
        """Jev 任务前校验配置。"""
        problems = []
        if not self.jev_api_key:
            problems.append("jev.api_key 为空")
        elif self.jev_api_key.startswith("在这里填"):
            problems.append("jev.api_key 仍是占位符，请在 config.ini 中填入真实 Key")
        if not self.jev_base_url.startswith("http"):
            problems.append(f"jev.base_url 格式不对：{self.jev_base_url}")
        if not self.jev_model:
            problems.append("jev.model 为空")
        if problems:
            raise ValueError(
                "Jev 配置校验失败：\n  - " + "\n  - ".join(problems) +
                f"\n\n请编辑配置文件：{self.path}")

    # ---------------- 校验 ----------------
    def validate_llm(self) -> None:
        """LLM 任务前校验配置，给出可操作的错误提示。"""
        problems = []
        if not self.llm_api_key:
            problems.append("llm.api_key 为空")
        elif self.llm_api_key.startswith("在这里填"):
            problems.append(
                "llm.api_key 仍是占位符，请在 config.ini 中填入真实 Key")
        if not self.llm_model:
            problems.append("llm.model 为空")
        if not self.llm_base_url.startswith("http"):
            problems.append(f"llm.base_url 格式不对：{self.llm_base_url}")
        if problems:
            raise ValueError(
                "配置校验失败：\n  - " + "\n  - ".join(problems) +
                f"\n\n请编辑配置文件：{self.path}")
        if not self.path.exists():  # pragma: no cover
            raise FileNotFoundError(self.path)

    def mask_key(self) -> str:
        """脱敏显示 Key，用于日志。"""
        k = self.llm_api_key
        return f"{k[:6]}***{k[-4:]}" if len(k) > 12 else "***"


CFG: Config | None = None


def get_config(reload: bool = False) -> Config:
    global CFG
    if CFG is None or reload:
        CFG = Config()
    return CFG