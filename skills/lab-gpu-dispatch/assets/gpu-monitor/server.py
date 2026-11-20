#!/usr/bin/env python3
"""在本机浏览器中查看个人 GPU 池。"""

import argparse
import csv
import getpass
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Lock
from time import monotonic

# 本机可用环境变量补充尚未配置的 SSH 别名，仓库只定义别名。
G130_35_HOST = os.environ.get("GPU_MONITOR_G130_35_HOST") or "g130-35"
HOSTS = (
    ("g130-40", "andrew@g130-40", "g130-40"),
    ("g130-51", "andrew@g130-51", "g130-51"),
    ("g130-35", f"andrew@{G130_35_HOST}", "g130-35"),
    ("本机", None, "本地 NVIDIA 驱动"),
)
ASSETS = Path(__file__).with_name("dist")
CACHE_SECONDS = 4  # 合并多个浏览器窗口的并发采样请求。
LOW_MEMORY_MIB = 512  # 允许驱动和桌面保留少量显存。
LOW_UTILIZATION = 5  # 利用率阈值，单位为百分比。
PROBE = """export LC_ALL=C
nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits || exit $?
printf '\\n__GPU_PROCESSES__\\n'
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory --format=csv,noheader,nounits || printf '\\n__PROCESS_ERROR__\\n'
"""


def integer(field):
    """
    将 NVIDIA 查询字段转为整数。
    输入单个 CSV 字段，输出整数，缺失指标返回 None。
    """
    field = field.strip()
    return int(field) if field.isdecimal() else None


def parse_probe(output):
    """
    解析一次 GPU 与计算进程的采样。
    输入采样命令的标准输出，返回按 GPU 序号排序的指标和进程。
    """
    gpu_csv, marker, process_csv = output.partition("__GPU_PROCESSES__")
    if not marker:
        raise ValueError("显卡采样输出不完整")
    processes = {}
    process_known = "__PROCESS_ERROR__" not in process_csv
    for row in csv.reader(process_csv.splitlines(), skipinitialspace=True):
        if not row:
            continue
        if len(row) != 4 or integer(row[1]) is None:
            process_known = False
            continue
        uuid, pid, name, memory = row
        processes.setdefault(uuid, []).append({
            "pid": integer(pid), "name": name.rsplit("/", 1)[-1], "memory": integer(memory),
        })

    gpus = []
    for row in csv.reader(gpu_csv.splitlines(), skipinitialspace=True):
        if not row:
            continue
        if len(row) != 7 or integer(row[0]) is None:
            raise ValueError("无法识别显卡采样字段")
        index, uuid, model, util, used, total, temp = row
        util, used, total, temp = map(integer, (util, used, total, temp))
        apps = processes.get(uuid, [])
        if apps or (util is not None and util > LOW_UTILIZATION) or (used is not None and used > LOW_MEMORY_MIB):
            status = "active"
        elif process_known and util is not None and used is not None:
            status = "low"
        else:
            status = "unknown"
        gpus.append({
            "index": integer(index), "model": model.removeprefix("NVIDIA GeForce "),
            "util": util, "used": used, "total": total, "temp": temp,
            "status": status, "processes": apps, "process_known": process_known,
        })
    return sorted(gpus, key=lambda gpu: gpu["index"])


class Pool:
    def __init__(self, password):
        """
        建立一次看板运行的采样状态。
        输入可选的 g130-35 登陆密码，在内存保存凭据和最近快照。
        """
        self.password = password
        self.lock = Lock()
        self.cached_at = -CACHE_SECONDS
        self.cached = None

    def probe(self, host):
        """
        对一台固定主机执行只读采样。
        输入主机配置，输出 GPU 指标或可诊断的主机状态。
        """
        label, target, address = host
        result = {"name": label, "address": address, "remote": target is not None, "gpus": []}
        command = ["sh", "-c", PROBE]
        password = self.password if label == "g130-35" else None
        if target:
            command = [
                "ssh", "-n", "-T", "-o", "StrictHostKeyChecking=yes",
                "-o", "ClearAllForwardings=yes", "-o", "ConnectTimeout=4",
                "-o", "NumberOfPasswordPrompts=1",
                "-o", f"BatchMode={'no' if password else 'yes'}",
            ]
            if password:
                command = ["sshpass", "-d", "0", *command, "-o", "PreferredAuthentications=password,keyboard-interactive"]
            command += [target, PROBE]

        try:
            sample = subprocess.run(
                command, input=f"{password}\n" if password else "",
                capture_output=True, text=True, errors="replace", timeout=9,
            )
        except subprocess.TimeoutExpired:
            return {**result, "state": "error", "message": "采样超时，请检查网络或 NVIDIA 驱动。"}
        except OSError:
            return {**result, "state": "error", "message": "无法启动本机采样命令。"}

        if sample.returncode:
            output = f"{sample.stderr}\n{sample.stdout}".lower()
            if "host key verification failed" in output or "host identification has changed" in output or (password and sample.returncode in {6, 7} and "nvidia" not in output):
                return {**result, "state": "error", "message": "SSH 主机指纹校验失败，请核对本机 SSH 记录。"}
            if "permission denied" in output or (password and sample.returncode == 5):
                if password:
                    self.password = None  # 认证失败后停止自动重试该密码，避免账户锁定。
                return {**result, "state": "auth", "message": "SSH 认证失败。可用终端密码模式重新启动看板。"}
            if target and sample.returncode == 255:
                return {**result, "state": "error", "message": "SSH 连接失败，请检查实验室网络或 VPN。"}
            return {**result, "state": "error", "message": "NVIDIA 驱动查询失败，请在该主机检查 nvidia-smi。"}

        try:
            gpus = parse_probe(sample.stdout)
        except ValueError as error:
            return {**result, "state": "error", "message": str(error)}
        return {
            **result, "state": "online", "gpus": gpus,
            "message": "" if gpus else "驱动未报告可监控的 GPU。",
        }

    def snapshot(self):
        """
        并行采样四台主机，并合并短时间内的重复请求。
        不接收浏览器参数，输出同一批采样结果和 UTC 时间。
        """
        with self.lock:
            if self.cached is None or monotonic() - self.cached_at >= CACHE_SECONDS:
                with ThreadPoolExecutor(max_workers=len(HOSTS)) as workers:
                    hosts = list(workers.map(self.probe, HOSTS))
                self.cached = {
                    "sampled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "hosts": hosts,
                }
                self.cached_at = monotonic()
            return self.cached


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """
        处理本机浏览器的固定只读 GET 路由。
        输入 HTTP 请求，输出界面资源或最新快照。
        """
        port = self.server.server_port
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self.send_error(403)
            return

        if self.path == "/api/status":
            mime = "application/json; charset=utf-8"
            body = json.dumps(self.server.pool.snapshot(), ensure_ascii=False).encode()
        else:
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
            }
            if self.path not in assets:
                self.send_error(404)
                return
            filename, mime = assets[self.path]
            body = (ASSETS / filename).read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """
        保持终端只显示启动信息和异常。
        接收默认 HTTP 日志参数，忽略例行轮询日志。
        """


def main():
    """
    读取启动参数，必要时从终端隐藏输入密码。
    启动回环地址的 HTTP 服务，Ctrl+C 时关闭。
    """
    parser = argparse.ArgumentParser(description="个人 GPU 看板")
    parser.add_argument("--port", type=int, default=8765, help="本地 HTTP 端口")
    parser.add_argument("--password-35", action="store_true", help="启动时在终端隐藏输入 g130-35 的密码")
    parser.add_argument("--open-in-edge", action="store_true", help="服务就绪后打开 Edge 应用窗口")
    args = parser.parse_args()
    password = None
    try:
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
            if args.password_35:
                if shutil.which("sshpass") is None:
                    parser.error("密码模式需要 sshpass")
                password = getpass.getpass("g130-35 SSH 密码（隐藏输入）: ")
            server.pool = Pool(password)
            url = f"http://127.0.0.1:{server.server_port}"
            print(f"个人 GPU 看板：{url}  按 Ctrl+C 停止", flush=True)
            if args.open_in_edge:
                try:
                    # 浏览器窗口和终端服务有各自的生命周期。
                    subprocess.Popen(
                        [sys.executable, "-B", str(Path(__file__).with_name("edge-app.py")), url],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                except OSError as error:
                    print(f"Edge 启动失败，请手动打开 {url}。{error}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
