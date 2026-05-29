#!/usr/bin/env python3
"""
更新 README.md 版本亮点表 (发版时自动调用)。

用法:
    python3 scripts/update_readme.py 5.2.0 "性能与鲁棒性增强"
    python3 scripts/update_readme.py 5.2.0  # 从 CHANGELOG 自动提取描述
"""
import re
import sys
import os

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(REPO_DIR, "README.md")
CHANGELOG_PATH = os.path.join(REPO_DIR, "CHANGELOG.md")


def get_description(version: str, fallback: str = "") -> str:
    """从 CHANGELOG.md 或 git tag 提取版本描述。"""
    # 1. 从 CHANGELOG 提取
    if os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, encoding="utf-8") as f:
            content = f.read()
        # 匹配: ## [5.2.0] 或 ## [5.2.0] - 2026-01-01
        pattern = rf"##\s*\[{re.escape(version)}\].*?\n+(.*?)(?=\n##\s*\[|\Z)"
        m = re.search(pattern, content, re.DOTALL)
        if m:
            desc = m.group(1).strip()
            # 提取第一行有意义的内容
            for line in desc.split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line and len(line) > 3:
                    return line[:80]  # 截断到 80 字符

        # 2. 从 CHANGELOG 的 emoji 行提取
        emoji_pattern = rf"##\s*\[{re.escape(version)}\].*?\n+.*?([🔖🔧🐛✨🚀🧪📝].*?)(?:\n|$)"
        m = re.search(emoji_pattern, content, re.DOTALL)
        if m:
            desc = m.group(1).strip()
            if len(desc) > 3:
                return desc[:80]

    # 3. 从 git tag 提取
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s", f"v{version}"],
            capture_output=True, text=True, timeout=5, cwd=REPO_DIR
        )
        if result.returncode == 0 and result.stdout.strip():
            msg = result.stdout.strip()
            # 移除版本前缀
            msg = re.sub(r'^v?\d+\.\d+\.\d+[:：\s]*', '', msg)
            msg = re.sub(r'^[🔖]\s*', '', msg)
            if len(msg) > 3:
                return msg[:80]
    except Exception:
        pass

    return fallback or "新版本发布"


def update_readme(version: str, description: str = "") -> None:
    """更新 README.md 中的版本亮点表。"""
    if not description:
        description = get_description(version)

    with open(README_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    # 找到版本亮点表并插入新行
    # 表格结构:
    #   | 版本 | 特性 |
    #   |------|------|
    #   | **v5.1.0** 🆕 | ... |
    #   | **v5.0.0** | ... |

    table_header_found = False
    table_divider_found = False
    insert_idx = -1
    existing_versions = set()
    max_rows = 8  # 最多保留 8 行

    for i, line in enumerate(lines):
        # 检测表格头
        if "| 版本 | 特性 |" in line:
            table_header_found = True
            continue
        if table_header_found and "|------|------|" in line:
            table_divider_found = True
            insert_idx = i + 1  # 在分割线后插入
            continue
        if table_divider_found:
            # 检测已有版本行
            m = re.match(r'\|\s*\*\*(v?\d+\.\d+\.\d+)\*\*.*\|\s*(.+?)\s*\|', line)
            if m:
                existing_versions.add(m.group(1).lstrip("v"))
                continue
            # 表格结束 (空行或非表格行)
            if not line.strip().startswith("|"):
                break

    if insert_idx < 0:
        print("⚠️  未找到版本亮点表, 跳过 README 更新")
        return

    # 检查版本是否已存在
    if version in existing_versions:
        print(f"⚠️  v{version} 已在版本表中, 跳过")
        return

    # 构建新行
    new_row = f"| **v{version}** 🆕 | {description} |\n"

    # 移除旧的 🆕 标记 (如果有的话)
    for i in range(len(lines)):
        if "🆕" in lines[i] and "| **v" in lines[i]:
            lines[i] = lines[i].replace(" 🆕 |", " |")

    # 在表格第一行插入新版本
    lines.insert(insert_idx, new_row)

    # 截断多余行 (保留最近 max_rows 个版本)
    row_count = 0
    remove_from = -1
    in_table = False
    for i, line in enumerate(lines):
        if "| 版本 | 特性 |" in line:
            in_table = True
            continue
        if in_table and "|------|------|" in line:
            continue
        if in_table:
            if line.strip().startswith("| **v"):
                row_count += 1
                if row_count > max_rows:
                    remove_from = i
                    break
            elif not line.strip().startswith("|"):
                break

    if remove_from > 0:
        # 删掉 remove_from 行
        end = remove_from
        while end < len(lines) and lines[end].strip().startswith("| **v"):
            end += 1
        del lines[remove_from:end]

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"✅ README.md 版本亮点表已更新: v{version} — {description}")


def update_changelog(version: str, description: str = "") -> None:
    """在 CHANGELOG.md 顶部插入新版本条目 (不覆盖已有内容)。"""
    from datetime import date
    today = date.today().isoformat()

    if not description:
        description = get_description(version, "新版本发布")

    if not os.path.exists(CHANGELOG_PATH):
        # 新建
        with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
            f.write("# Changelog\n\n")
            f.write("所有 notable 变更均记录在此文件。\n\n")
            f.write("格式基于 [Keep a Changelog](https://keepachangelog.com/),\n")
            f.write("版本号遵循 [Semantic Versioning](https://semver.org/).\n\n")
            f.write(f"## [{version}] - {today}\n\n")
            f.write(f"- {description}\n\n")
        print(f"✅ CHANGELOG.md 已创建: v{version}")
        return

    with open(CHANGELOG_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    # 查找第一个版本标题的位置 (## [x.x.x])
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            insert_idx = i + 1
        if line.startswith("## ["):
            insert_idx = i
            break
    else:
        # 没找到版本标题, 插在文件末尾
        insert_idx = len(lines)

    # 检查版本是否已存在
    version_header = f"## [{version}]"
    for line in lines:
        if line.startswith(version_header):
            print(f"⚠️  CHANGELOG.md 中 v{version} 已存在, 跳过")
            return

    # 插入新条目
    entry = [
        f"\n## [{version}] - {today}\n",
        "\n",
        f"- {description}\n",
        "\n",
    ]

    for i, item in enumerate(reversed(entry)):
        lines.insert(insert_idx, item)

    with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"✅ CHANGELOG.md 已更新: v{version}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 scripts/update_readme.py <版本号> [描述]")
        print("示例: python3 scripts/update_readme.py 5.2.0 '性能与鲁棒性增强'")
        sys.exit(1)

    ver = sys.argv[1]
    desc = sys.argv[2] if len(sys.argv) > 2 else ""

    update_changelog(ver, desc)
    update_readme(ver, desc)
    print("✅ 文档更新完成")
