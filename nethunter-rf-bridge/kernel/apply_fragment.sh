#!/usr/bin/env bash
# Merge kernel/subgdev.config into your NetHunter kernel defconfig.
#   kernel/apply_fragment.sh <kernel-source-dir> <defconfig-name>
#   e.g. kernel/apply_fragment.sh ~/android/kernel_xyz nethunter_defconfig
# Backs up the defconfig, merges, verifies every symbol survived Kconfig.
set -euo pipefail
KSRC="${1:?kernel source dir}"; DEFCONFIG="${2:?defconfig name (arch/arm64/configs/...)}"
ARCH="${ARCH:-arm64}"
FRAG="$(cd "$(dirname "$0")" && pwd)/subgdev.config"
DC="$KSRC/arch/$ARCH/configs/$DEFCONFIG"
[ -f "$DC" ] || { echo "not found: $DC" >&2; exit 1; }
cp "$DC" "$DC.bak-subgdev"
OUT="$(mktemp -d)"
( cd "$KSRC" && ARCH=$ARCH scripts/kconfig/merge_config.sh -m -O "$OUT" "$DC" "$FRAG" >/dev/null \
  && make ARCH=$ARCH O="$OUT" olddefconfig >/dev/null && make ARCH=$ARCH O="$OUT" savedefconfig >/dev/null )
missing=0
while IFS= read -r line; do
  case "$line" in CONFIG_*=y) grep -qx "$line" "$OUT/.config" || { echo "WARN: $line dropped by Kconfig (missing dependency?)"; missing=1; };; esac
done < "$FRAG"
cp "$OUT/defconfig" "$DC"
echo "Updated $DC (backup: $DC.bak-subgdev)"
[ $missing = 0 ] && echo "All subGdev symbols enabled. Rebuild and flash your NetHunter kernel." || exit 2
