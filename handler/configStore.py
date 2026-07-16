# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     configStore
   Description :   运行时配置持久化（网页表单保存）
   Author :        JHao
   date：          2026/7/16
-------------------------------------------------
"""
__author__ = "JHao"

import json
import os
import tempfile
from copy import deepcopy

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_data_dir():
    return os.environ.get("PROXY_POOL_DATA_DIR") or os.path.join(PROJECT_ROOT, "data")


def get_config_file():
    return os.environ.get("PROXY_POOL_CONFIG_FILE") or os.path.join(get_data_dir(), "runtime_config.json")


# 动态属性兼容：configStore.CONFIG_FILE / DATA_DIR
class _Dyn(object):
    def __init__(self, fn):
        self._fn = fn
    def __str__(self):
        return self._fn()
    def __fspath__(self):
        return self._fn()
    def __repr__(self):
        return self._fn()
    def __eq__(self, other):
        return self._fn() == other
    def __hash__(self):
        return hash(self._fn())


DATA_DIR = _Dyn(get_data_dir)
CONFIG_FILE = _Dyn(get_config_file)

# 可在网页配置并持久化的字段定义
# restart_required: 改完建议重启进程才完全生效（部分会热加载）
CONFIG_SCHEMA = [
    {
        "key": "HOST",
        "label": "监听地址",
        "group": "服务",
        "type": "str",
        "default_attr": "HOST",
        "env": "HOST",
        "restart_required": True,
        "help": "API 监听 IP。本机访问可用 127.0.0.1，远程访问用 0.0.0.0",
    },
    {
        "key": "PORT",
        "label": "监听端口",
        "group": "服务",
        "type": "int",
        "default_attr": "PORT",
        "env": "PORT",
        "restart_required": True,
        "help": "API 服务端口",
    },
    {
        "key": "API_TOKEN",
        "label": "API Token",
        "group": "服务",
        "type": "password",
        "default_attr": "API_TOKEN",
        "env": "API_TOKEN",
        "restart_required": False,
        "help": "为空表示不鉴权。设置后业务接口与配置保存都需要该 Token",
    },
    {
        "key": "DB_CONN",
        "label": "数据库连接",
        "group": "数据库",
        "type": "str",
        "default_attr": "DB_CONN",
        "env": "DB_CONN",
        "restart_required": False,
        "help": "如 redis://:password@127.0.0.1:6379/0",
    },
    {
        "key": "TABLE_NAME",
        "label": "数据表名",
        "group": "数据库",
        "type": "str",
        "default_attr": "TABLE_NAME",
        "env": "TABLE_NAME",
        "restart_required": False,
        "help": "Redis/SSDB hash 名称",
    },
    {
        "key": "PROXY_FETCHER_EXCLUDE",
        "label": "禁用代理源",
        "group": "采集",
        "type": "list",
        "default_attr": "PROXY_FETCHER_EXCLUDE",
        "env": None,
        "restart_required": False,
        "help": "逗号分隔，支持 name 或类名，如 freevpnnode,KuaidailiFetcher",
    },
    {
        "key": "HTTP_URL",
        "label": "HTTP 校验地址",
        "group": "校验",
        "type": "str",
        "default_attr": "HTTP_URL",
        "env": "HTTP_URL",
        "restart_required": False,
        "help": "建议改成业务真实访问的站点",
    },
    {
        "key": "HTTPS_URL",
        "label": "HTTPS 校验地址",
        "group": "校验",
        "type": "str",
        "default_attr": "HTTPS_URL",
        "env": "HTTPS_URL",
        "restart_required": False,
        "help": "用于检测代理是否支持 HTTPS",
    },
    {
        "key": "VERIFY_TIMEOUT",
        "label": "校验超时(秒)",
        "group": "校验",
        "type": "int",
        "default_attr": "VERIFY_TIMEOUT",
        "env": "VERIFY_TIMEOUT",
        "restart_required": False,
        "help": "超时视为代理不可用",
    },
    {
        "key": "MAX_FAIL_COUNT",
        "label": "最大失败次数",
        "group": "校验",
        "type": "int",
        "default_attr": "MAX_FAIL_COUNT",
        "env": "MAX_FAIL_COUNT",
        "restart_required": False,
        "help": "超过后删除代理；0 表示失败一次即删",
    },
    {
        "key": "POOL_SIZE_MIN",
        "label": "最小池容量",
        "group": "校验",
        "type": "int",
        "default_attr": "POOL_SIZE_MIN",
        "env": "POOL_SIZE_MIN",
        "restart_required": False,
        "help": "检查时若代理数少于此值，先触发抓取",
    },
    {
        "key": "CHECK_THREAD_COUNT",
        "label": "校验线程数",
        "group": "校验",
        "type": "int",
        "default_attr": "CHECK_THREAD_COUNT",
        "env": "CHECK_THREAD_COUNT",
        "restart_required": False,
        "help": "并发校验线程数",
    },
    {
        "key": "PROXY_REGION",
        "label": "解析地域",
        "group": "校验",
        "type": "bool",
        "default_attr": "PROXY_REGION",
        "env": "PROXY_REGION",
        "restart_required": False,
        "help": "是否解析代理 IP 国家/地区",
    },
    {
        "key": "TIMEZONE",
        "label": "时区",
        "group": "调度",
        "type": "str",
        "default_attr": "TIMEZONE",
        "env": "TIMEZONE",
        "restart_required": True,
        "help": "调度器时区，如 Asia/Shanghai",
    },
    {
        "key": "FETCH_INTERVAL_MINUTES",
        "label": "采集间隔(分钟)",
        "group": "调度",
        "type": "int",
        "default_attr": "FETCH_INTERVAL_MINUTES",
        "env": "FETCH_INTERVAL_MINUTES",
        "restart_required": True,
        "help": "定时采集任务间隔；改后需重启 schedule 进程",
    },
    {
        "key": "CHECK_INTERVAL_MINUTES",
        "label": "检查间隔(分钟)",
        "group": "调度",
        "type": "int",
        "default_attr": "CHECK_INTERVAL_MINUTES",
        "env": "CHECK_INTERVAL_MINUTES",
        "restart_required": True,
        "help": "定时检查任务间隔；改后需重启 schedule 进程",
    },
    {
        "key": "SCHEDULER_MAX_INSTANCES",
        "label": "任务最大并行",
        "group": "调度",
        "type": "int",
        "default_attr": "SCHEDULER_MAX_INSTANCES",
        "env": "SCHEDULER_MAX_INSTANCES",
        "restart_required": True,
        "help": "同一任务最大并行实例，建议 1",
    },
]

_SCHEMA_MAP = {item["key"]: item for item in CONFIG_SCHEMA}
_runtime_cache = None
_runtime_mtime = None


def _ensure_data_dir():
    if not os.path.isdir(get_data_dir()):
        os.makedirs(get_data_dir(), exist_ok=True)


def _setting_default(attr_name):
    import setting
    return getattr(setting, attr_name, None)


def clear_runtime_cache():
    global _runtime_cache, _runtime_mtime
    _runtime_cache = None
    _runtime_mtime = None


def load_runtime_config(force=False):
    """读取 data/runtime_config.json，不存在返回空 dict"""
    global _runtime_cache, _runtime_mtime
    if not force and _runtime_cache is not None:
        try:
            mtime = os.path.getmtime(get_config_file()) if os.path.isfile(get_config_file()) else None
            if mtime == _runtime_mtime:
                return deepcopy(_runtime_cache)
        except OSError:
            pass

    data = {}
    mtime = None
    if os.path.isfile(get_config_file()):
        try:
            mtime = os.path.getmtime(get_config_file())
            with open(get_config_file(), "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data = raw
        except Exception:
            data = {}

    _runtime_cache = data
    _runtime_mtime = mtime
    return deepcopy(data)


def _parse_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off", ""):
        return False
    return bool(default)


def _parse_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).replace("\n", ",").replace(";", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def normalize_value(key, value):
    """按 schema 规范化单个配置值"""
    meta = _SCHEMA_MAP.get(key)
    if not meta:
        raise ValueError("unsupported config key: %s" % key)
    t = meta["type"]
    if t == "str" or t == "password":
        if value is None:
            return ""
        return str(value).strip()
    if t == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError("%s must be integer" % key)
    if t == "bool":
        return _parse_bool(value, False)
    if t == "list":
        return _parse_list(value)
    raise ValueError("unknown type for %s" % key)


def validate_payload(payload):
    """校验并规范化提交的配置字典，返回 (clean, errors)"""
    if not isinstance(payload, dict):
        return {}, ["payload must be object"]

    clean = {}
    errors = []
    for key, raw in payload.items():
        if key not in _SCHEMA_MAP:
            errors.append("unknown key: %s" % key)
            continue
        try:
            clean[key] = normalize_value(key, raw)
        except ValueError as e:
            errors.append(str(e))

    # 业务约束
    if "PORT" in clean:
        if not (1 <= clean["PORT"] <= 65535):
            errors.append("PORT must be between 1 and 65535")
    for key in ("VERIFY_TIMEOUT", "POOL_SIZE_MIN", "CHECK_THREAD_COUNT",
                "FETCH_INTERVAL_MINUTES", "CHECK_INTERVAL_MINUTES", "SCHEDULER_MAX_INSTANCES"):
        if key in clean and clean[key] < 1:
            errors.append("%s must be >= 1" % key)
    if "MAX_FAIL_COUNT" in clean and clean["MAX_FAIL_COUNT"] < 0:
        errors.append("MAX_FAIL_COUNT must be >= 0")
    if "DB_CONN" in clean and clean["DB_CONN"]:
        scheme = clean["DB_CONN"].split("://", 1)[0].lower()
        if scheme not in ("redis", "ssdb"):
            errors.append("DB_CONN scheme must be redis or ssdb")

    return clean, errors


def save_runtime_config(payload, merge=True):
    """
    保存配置到 JSON 文件。
    merge=True 时与已有文件合并；False 时仅保存提交字段（仍只保留 schema 内 key）。
    返回最终文件内容。
    """
    clean, errors = validate_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))

    current = load_runtime_config(force=True) if merge else {}
    current.update(clean)

    # 只保留 schema 中的 key
    final = {}
    for key in _SCHEMA_MAP:
        if key in current:
            final[key] = normalize_value(key, current[key])

    _ensure_data_dir()
    # 原子写入
    fd, tmp_path = tempfile.mkstemp(prefix="runtime_config_", suffix=".json", dir=get_data_dir())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(final, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, get_config_file())
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise

    clear_runtime_cache()
    return load_runtime_config(force=True)


def get_field_source(key, runtime_cfg=None):
    """返回配置来源: env / runtime / default"""
    meta = _SCHEMA_MAP[key]
    env_name = meta.get("env")
    if env_name and os.environ.get(env_name) is not None:
        return "env"
    runtime_cfg = runtime_cfg if runtime_cfg is not None else load_runtime_config()
    if key in runtime_cfg:
        return "runtime"
    return "default"


def get_effective_value(key, runtime_cfg=None):
    """计算生效值：env > runtime_config > setting.py"""
    meta = _SCHEMA_MAP[key]
    runtime_cfg = runtime_cfg if runtime_cfg is not None else load_runtime_config()
    default = _setting_default(meta["default_attr"])
    source = get_field_source(key, runtime_cfg)

    if source == "env":
        raw = os.environ.get(meta["env"])
        return normalize_value(key, raw), source
    if source == "runtime":
        return normalize_value(key, runtime_cfg[key]), source
    # default 也规范化，list/bool 等
    try:
        return normalize_value(key, default), source
    except Exception:
        return default, source


def build_config_view(mask_secrets=False):
    """供管理页/API 展示的完整配置视图"""
    runtime_cfg = load_runtime_config()
    fields = []
    values = {}
    for meta in CONFIG_SCHEMA:
        key = meta["key"]
        value, source = get_effective_value(key, runtime_cfg)
        display = value
        if mask_secrets and meta["type"] == "password" and value:
            display = "********"
        item = {
            "key": key,
            "label": meta["label"],
            "group": meta["group"],
            "type": meta["type"],
            "help": meta["help"],
            "restart_required": meta["restart_required"],
            "value": display,
            "raw_value": value if not (mask_secrets and meta["type"] == "password") else None,
            "source": source,
            "locked": source == "env",
            "env": meta.get("env"),
        }
        # list 在表单中展示为逗号串
        if meta["type"] == "list" and isinstance(display, list):
            item["value"] = ",".join(display)
            item["raw_value"] = display
        fields.append(item)
        values[key] = item["value"] if meta["type"] != "password" or not mask_secrets else display

    return {
        "file": str(get_config_file()),
        "exists": os.path.isfile(get_config_file()),
        "fields": fields,
        "values": values,
    }


def apply_saved_to_setting_module(runtime_cfg=None):
    """
    将 runtime 配置同步到 setting 模块属性（不覆盖 env 锁定项）。
    便于旧代码直接 import setting.XXX 时也能读到最新值。
    """
    import setting
    runtime_cfg = runtime_cfg if runtime_cfg is not None else load_runtime_config()
    for meta in CONFIG_SCHEMA:
        key = meta["key"]
        if get_field_source(key, runtime_cfg) == "env":
            continue
        value, _ = get_effective_value(key, runtime_cfg)
        setattr(setting, key, value)
