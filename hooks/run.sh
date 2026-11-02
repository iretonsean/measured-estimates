#!/bin/sh
# measured-estimates hook wrapper (REQ-02). It never fails and never prints.
# It finds a real python3. On macOS without the developer tools, /usr/bin/python3 is a stub that opens a system
# dialog, so the wrapper never runs it there. With no usable python3 it reads its input and exits 0.
mode="$1"
here=$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || { cat >/dev/null 2>&1; exit 0; }
sys_py="${ME_SYSTEM_PYTHON:-/usr/bin/python3}"
os_name="${ME_UNAME:-$(uname -s 2>/dev/null)}"
xcs="${ME_XCODE_SELECT:-xcode-select}"
fallback="${ME_FALLBACK_DIRS-/opt/homebrew/bin:/usr/local/bin:/usr/bin}"

skip_stub=0
if [ "$os_name" = "Darwin" ]; then
  "$xcs" -p >/dev/null 2>&1 || skip_stub=1
fi

py=""
old_ifs=$IFS
IFS=:
for d in $PATH:$fallback; do
  case "$d" in /*) ;; *) continue;; esac   # only absolute folders: never a python3 in the project folder
  c="$d/python3"
  [ -x "$c" ] || continue
  if [ "$skip_stub" = 1 ] && [ "$c" = "$sys_py" ]; then continue; fi
  "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1 </dev/null || continue
  py="$c"
  break
done
IFS=$old_ifs

if [ -z "$py" ]; then
  cat >/dev/null 2>&1
  exit 0
fi
"$py" "$here/../scripts/record.py" "$mode" >/dev/null 2>&1
exit 0
