#!/usr/bin/env bash
set -eu

root="$(dirname -- "$(realpath -- "$0")")"
url=http://127.0.0.1:8765

# 确认端口对应本看板，再复用现有服务。
if page="$(curl --noproxy '*' -fs --max-time 2 "$url/")"; then
    if [[ "$page" == *'<title>Andrew · GPU 资源看板</title>'* ]]; then
        exec python3 -B "$root/edge-app.py" "$url"
    fi
fi

# 冷启动时在终端隐藏输入 SSH 密码。
exec gnome-terminal --title="个人 GPU 看板服务" -- python3 -B "$root/server.py" --password-35 --open-in-edge
