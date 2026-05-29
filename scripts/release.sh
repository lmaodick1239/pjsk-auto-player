#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# PJSK Auto Player — 一键发版脚本
# ═══════════════════════════════════════════════════════════════════
#
# 功能:
#   1. 更新 VERSION 文件
#   2. 自动生成 CHANGELOG.md / 更新 README 版本表
#   3. git commit + tag
#   4. git push → GitHub Actions 自动构建 & 发布 Release
#
# 用法:
#   ./scripts/release.sh <新版本号> [commit-message] [--allow-dirty] [--dry-run]
#
# 示例:
#   ./scripts/release.sh 5.2.0
#   ./scripts/release.sh 5.2.0 "v5.2.0: 性能与鲁棒性增强"
#   ./scripts/release.sh 5.2.0 -y          (全自动, 跳过确认)
#
# 前置条件:
#   - git remote origin 已配置
#   - 当前分支无未提交的变更 (或使用 --allow-dirty)
#   - 有权限 push 到 origin
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── 参数解析 ──
NEW_VERSION=""
COMMIT_MSG=""
ALLOW_DIRTY=false
DRY_RUN=false
AUTO_YES=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-dirty) ALLOW_DIRTY=true; shift ;;
        --dry-run)     DRY_RUN=true; shift ;;
        -y|--yes)      AUTO_YES=true; shift ;;
        -m|--message)
            COMMIT_MSG="$2"
            shift 2 ;;
        *)
            if [ -z "$NEW_VERSION" ]; then
                NEW_VERSION="$1"
            else
                # 剩余参数合并为 commit message
                if [ -z "$COMMIT_MSG" ]; then
                    COMMIT_MSG="$1"
                else
                    COMMIT_MSG="$COMMIT_MSG $1"
                fi
            fi
            shift ;;
    esac
done

if [ -z "$NEW_VERSION" ]; then
    CURRENT=$(cat VERSION 2>/dev/null || echo "未知")
    echo "当前版本: v$CURRENT"
    echo ""
    echo "用法: $0 <新版本号> [--allow-dirty] [--dry-run]"
    echo ""
    echo "示例:"
    echo "  $0 5.2.0"
    echo "  $0 5.2.0 --dry-run"
    exit 1
fi

# ── 前置检查 ──
echo ""
info "=========================================="
info "  PJSK Auto Player 发版流程"
info "  版本: v$NEW_VERSION"
info "=========================================="
echo ""

# 1. git 仓库
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    err "当前目录不是 git 仓库"; exit 1
fi

# 2. 远程
REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [ -z "$REMOTE" ]; then
    err "未配置 git remote origin"; exit 1
fi
info "Remote: $REMOTE"

# 3. 分支
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "master" ]; then
    warn "当前分支: $BRANCH (非 main/master)"
    read -rp "  继续? [y/N] " confirm
    [ "$confirm" != "y" ] && [ "$confirm" != "Y" ] && { info "取消"; exit 0; }
fi

# 4. 工作区检查
if [ "$ALLOW_DIRTY" != "true" ]; then
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        warn "有未提交的变更:"
        git status --short
        echo ""
        read -rp "  先提交这些变更? [Y/n] " confirm
        if [ "$confirm" != "n" ] && [ "$confirm" != "N" ]; then
            err "请先 git add -A && git commit 或使用 --allow-dirty"; exit 1
        fi
    fi
fi

# 5. 版本格式
if ! echo "$NEW_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
    warn "版本号 '$NEW_VERSION' 不匹配 semver 格式 (X.Y.Z)"
    read -rp "  继续? [y/N] " confirm
    [ "$confirm" != "y" ] && [ "$confirm" != "Y" ] && { info "取消"; exit 0; }
fi

# 6. tag 重复检查
TAG="v$NEW_VERSION"
if git rev-parse "$TAG" >/dev/null 2>&1; then
    err "Tag $TAG 已存在"; exit 1
fi

# ── 执行 ──
if [ "$DRY_RUN" = "true" ]; then
    info "=== DRY RUN (不会实际执行) ==="
fi

# Step 1: VERSION
info "1/4 更新 VERSION: $NEW_VERSION"
if [ "$DRY_RUN" != "true" ]; then
    echo "$NEW_VERSION" > VERSION
fi
ok "VERSION → $NEW_VERSION"

# Step 2: 更新 CHANGELOG.md + README.md
info "2/4 更新文档 (CHANGELOG + README)..."
DESC="${COMMIT_MSG#🔖 }"
DESC="${DESC#v$NEW_VERSION}"
DESC="${DESC#v$NEW_VERSION: }"
DESC="${DESC#v$NEW_VERSION — }"
DESC="${DESC## }"
if [ "$DRY_RUN" != "true" ]; then
    python3 scripts/update_readme.py "$NEW_VERSION" "$DESC" 2>/dev/null || {
        warn "update_readme.py 失败, 尝试 fallback gen_changelog.sh"
        [ -x scripts/gen_changelog.sh ] && bash scripts/gen_changelog.sh || true
    }
fi
ok "文档已更新"

# Step 3: Commit
[ -z "$COMMIT_MSG" ] && COMMIT_MSG="🔖 v$NEW_VERSION"
info "3/4 git commit: $COMMIT_MSG"

if [ "$DRY_RUN" != "true" ]; then
    git add VERSION CHANGELOG.md README.md 2>/dev/null || true
    git add -u 2>/dev/null || true
    if git diff --cached --quiet 2>/dev/null; then
        warn "没有需要提交的变更, 跳过 commit"
    else
        git commit -m "$COMMIT_MSG"
        ok "已提交"
    fi
fi

# Step 4: Tag + Push
info "4/4 git tag: $TAG"
DATE=$(date +%Y-%m-%d)

if [ "$DRY_RUN" != "true" ]; then
    git tag -a "$TAG" -m "v$NEW_VERSION ($DATE)

PJSK Auto Player v$NEW_VERSION 正式发布.
CI: GitHub Actions 将在 push 后自动构建 & 发版."
    ok "Tag 创建: $TAG"
fi

echo ""
echo "即将推送到 origin/$BRANCH + tag $TAG"
echo "推送后 GitHub Actions 会自动构建 Release."
if [ "$AUTO_YES" != "true" ]; then
    read -rp "确认推送? [Y/n] " confirm
    if [ "$confirm" = "n" ] || [ "$confirm" = "N" ]; then
        warn "跳过推送. 稍后可手动: git push origin $BRANCH --tags"
        exit 0
    fi
else
    info "自动确认推送 (-y)"
fi

if [ "$DRY_RUN" != "true" ]; then
    git push origin "$BRANCH"
    git push origin "$TAG"
    ok "推送完成!"
fi

echo ""
echo "═══════════════════════════════════════════"
echo -e "  ${GREEN}✅ 发版完成!${NC}"
echo ""
echo "  📦 v$NEW_VERSION  |  🔗 $TAG"
echo "  🌐 $REMOTE"
echo ""
echo "  CI 构建: $REMOTE/actions"
echo "═══════════════════════════════════════════"
