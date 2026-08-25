#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$DIR/.pid" ]; then
  kill "$(cat $DIR/.pid)" 2>/dev/null && rm -f "$DIR/.pid" && echo "已停止"
else
  echo "没有在运行"
fi
