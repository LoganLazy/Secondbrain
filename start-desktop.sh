#!/usr/bin/env bash
# Nebula Memory 桌面版启动器(Electron)
# 用法: ./start-desktop.sh
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PATH="$DIR/../runtime/node/bin:$PATH"

# 若系统缺GTK等库(如精简容器), 自动带上随包附带的库目录
if [ -d "$DIR/../guilibs/root/usr/lib/x86_64-linux-gnu" ]; then
  export LD_LIBRARY_PATH="$DIR/../guilibs/root/usr/lib/x86_64-linux-gnu:$DIR/../guilibs/root/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
fi

cd "$DIR"
exec node_modules/.bin/electron . "$@"
