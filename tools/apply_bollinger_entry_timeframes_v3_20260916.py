from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "tools" / "apply_bollinger_entry_timeframes_20260916.py"
V2_PATH = ROOT / "tools" / "apply_bollinger_entry_timeframes_v2_20260916.py"

base_spec = importlib.util.spec_from_file_location("bb_tf_base", BASE_PATH)
if base_spec is None or base_spec.loader is None:
    raise RuntimeError("cannot load base patcher")
base = importlib.util.module_from_spec(base_spec)
base_spec.loader.exec_module(base)

v2_spec = importlib.util.spec_from_file_location("bb_tf_v2", V2_PATH)
if v2_spec is None or v2_spec.loader is None:
    raise RuntimeError("cannot load v2 patcher")
v2 = importlib.util.module_from_spec(v2_spec)
v2_spec.loader.exec_module(v2)


def patch_bridge_effect() -> None:
    rel = "web/components/aster-profit-lock-ladder-bridge.tsx"
    text = base.read(rel)
    old = '''  useEffect(() => {\n    void refresh();\n    const timer = window.setInterval(() => void refresh(), 15000);\n    return () => window.clearInterval(timer);\n  }, [refresh]);'''
    new = '''  useEffect(() => {\n    const initial = window.setTimeout(() => { void refresh(); }, 0);\n    const timer = window.setInterval(() => void refresh(), 15000);\n    return () => {\n      window.clearTimeout(initial);\n      window.clearInterval(timer);\n    };\n  }, [refresh]);'''
    text = base.replace_once(text, old, new, "bridge initial refresh effect")
    base.write(rel, text)


def main() -> None:
    base.patch_backend()
    v2.patch_core()
    base.patch_card()
    base.patch_bridge()
    patch_bridge_effect()
    base.patch_tests()
    print("Applied selectable Bollinger entry timeframes v3 with lint-safe bridge refresh")


if __name__ == "__main__":
    main()
