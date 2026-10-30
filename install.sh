#!/usr/bin/env bash
# Install infinityoc-recover as a global opencode skill.
set -euo pipefail
TARGET="${HOME}/.config/opencode/skills/infinityoc-recover"
mkdir -p "$(dirname "$TARGET")"
rm -rf "$TARGET"
cp -r "$(cd "$(dirname "$0")" && pwd)" "$TARGET"
echo "installed: $TARGET"
echo "test:"
echo "  python3 $TARGET/scripts/recover.py <session-id-or-fragment>"
