#!/usr/bin/env python3
"""Update GitHub STORAGE_STATE secret from local storage_state.json.

Usage:
  uv run python scripts/refresh_secret.py
"""

import subprocess
import sys
from pathlib import Path

STORAGE_STATE_PATH = Path(__file__).resolve().parents[1] / "storage_state.json"


def main():
    if not STORAGE_STATE_PATH.exists():
        print(f"❌ {STORAGE_STATE_PATH} 不存在，請先執行 login_save_cookies.py")
        sys.exit(1)

    # Validate JSON
    import json
    try:
        with open(STORAGE_STATE_PATH) as f:
            json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ storage_state.json 不是有效 JSON: {e}")
        sys.exit(1)

    # Update GitHub secret
    print("正在更新 GitHub secret STORAGE_STATE...")
    result = subprocess.run(
        ["gh", "secret", "set", "STORAGE_STATE"],
        stdin=open(STORAGE_STATE_PATH),
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("✅ GitHub secret STORAGE_STATE 已更新！")
    else:
        print(f"❌ 更新失敗: {result.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    main()
