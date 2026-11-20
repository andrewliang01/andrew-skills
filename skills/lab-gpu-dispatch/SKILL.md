---
name: lab-gpu-dispatch
description: 查看 Andrew 的 g130-40、g130-51、g130-35 和本机 GPU，打开个人看板、核对显存或进程，或通过已确认的 lab-platform 分发、核验训练和评估任务。
---

# Andrew 的 GPU 资源与任务

## 查看资源

| 主机 | SSH 别名 | 已核验硬件 |
| --- | --- | --- |
| g130-40 | `andrew@g130-40` | 8 × RTX 4090 |
| g130-51 | `andrew@g130-51` | 2 × RTX 5090 |
| g130-35 | `andrew@g130-35` | 2 × RTX 4090 |
| 本机 | 直接查询 | 1 × RTX 5090 |

- Ubuntu 当前工作站可点击桌面或左侧 Dock 的「个人 GPU 看板」，在 Edge 专用窗口最大化打开并保留标题栏。服务运行时可打开 [本机看板](http://127.0.0.1:8765)。它通过 NVIDIA 驱动显示 GPU 利用率、显存、温度与计算进程，展开进程可查看用户名、进程名、PID 和显存。页面打开时每 15 秒采样。
- 先用现有 SSH 配置和本机 `nvidia-smi` 查询。核对别名、账号和主机指纹。g130-35 的内网地址从本机配置获取。g130-40 和 g130-51 已验证现有 SSH 密钥可用。g130-35 无可用密钥时让用户在终端隐藏输入密码。凭据只在本机认证流程中使用。
- 若需另装或恢复看板，使用随技能提供的 [看板源码](assets/gpu-monitor/server.py)。从技能根目录运行：

  ```bash
  python3 assets/gpu-monitor/server.py --password-35
  ```

  需要 Python 3.9+、SSH、`nvidia-smi`；g130-35 的密码模式还需要 `sshpass`。已有该节点的密钥时省略 `--password-35`。若系统没有 g130-35 别名，可在启动进程的环境里用 `GPU_MONITOR_G130_35_HOST` 指定已核验的地址或别名。服务只监听回环地址，默认端口 8765，端口冲突时用 `--port`。GNOME 和 Edge 下可运行 `bash assets/gpu-monitor/launch-desktop.sh`，启动器会复用已经运行的看板或打开终端提示。在 Ubuntu X11 会话里会将专用 Edge 窗口最大化。
- “低占用”表示无可见计算进程、GPU 利用率 ≤ 5%、显存占用 ≤ 512 MiB。用它初筛，再确认平台预留、CPU、主机内存和镜像兼容性。采样失败或占用未知时保留未知状态。静态硬件清单不能代替实时采样。

## 通过 lab-platform 分发任务

个人看板只读。用户要求提交任务时，从当前项目或已授权的环境核验自己的平台中心、CLI、API、镜像仓库、凭据来源和主机注册状态。以该实例的 `README.md`、`config.local.json`、`labplatform/core.py` 和实时 API 为准。平台主机 ID 由平台注册信息确定，可能与看板名称不同。Andrew 的个人平台中心当前部署在 `g130-51`，服务为 `andrew-lab-platform.service`。当前平台只登记该节点，本机和其他两台服务器仍可在看板查看。本工作站通过已安装的 `lab` SSH 入口访问。先运行 `lab health` 和 `lab config` 确认实例。用 `lab pool --refresh` 在中心查询资源和预留；`lab submit` 与 `lab results --output` 所用绝对路径位于中心。平台令牌在中心读取。

- 处于其他主机时，使用已核验的 SSH 连接在平台中心执行 CLI，或转发该中心的环回 API。任务 YAML 里的 `code` 和资产 `source` 取平台中心上允许访问的绝对路径。不要在看板所在机器上假定已部署中心。
- 用已确认实例的 `lab` CLI。已知协议的实例支持指定主机和 GPU。跨机自动选择、等待与重试由调用侧按用户授权实现。引擎本身无自动选机、排队、抢占或重试。

### 查询并筛选资源

```bash
lab hosts
lab gpu PLATFORM_HOST_ID
python3 scripts/pool_status.py --refresh --host PLATFORM_HOST_ID
python3 scripts/pool_status.py --min-free-mib 21000 --cpus 8 --memory-gib 32
```

脚本从技能根目录运行。先配置已核验的 `LAB_URL`，令牌用 `LAB_TOKEN_FILE`、`LAB_PLATFORM_DIR/.runtime/token` 或已有的 `LAB_TOKEN`，也可用 `--url`、`--token-file`、`--platform-dir`。用 `--host`、`--exclude-host` 限定范围，`--min-driver-major`、`--max-age` 检查驱动主版本和采样新鲜度。`--refresh` 仅刷新采样。确认训练入口、数据、输出、主机、GPU 数量和并行需求。

按用户指定主机和卡选择。候选机须在线、非维护、数据新鲜，Docker 可用，且 GPU 占用已知、空闲、无非终态任务预留。按任务核对 CPU、主机内存、显存、驱动和 GPU UUID。候选结果供准入前初筛，实际资源仍由平台在准入和容器启动前复查。

### 准备并提交

- 按 [任务规格与兼容性](references/task-spec.md) 准备镜像、代码和资产。固定镜像 digest，核对 CUDA、GPU 架构、驱动和容器实际加载的关键源码补丁。新组合在同一镜像内先执行代表性短测。
- 只快照必要普通文件，数据和权重使用不可变资产。容器代码目录 `/workspace` 和资产目录 `/inputs/<asset-id>` 只读，输出放在 `/outputs`。`cuda:0` 是容器分配后的逻辑编号。
- 沿用训练入口、实验名、`run_name`、记录器、在线项目、指标、step 和保存频率。需要训练期间增量回传时，提交前确认 `/outputs` 到原任务目录的映射并准备独立同步器。记录器及回传验收细节见任务规格。

```bash
lab submit /absolute/path/on/platform-center/task.yaml --host PLATFORM_HOST_ID --gpus 0
lab status TASK_ID
lab logs TASK_ID
```

也可通过已核验的 `POST /api/tasks` 提交等价 JSON。API 客户端关闭环境代理并设置超时，令牌留在认证流程里。提交前重查资源。在任务工程保存实际任务文件与台账，记录主机、GPU UUID、镜像 digest、资产 ID、任务 ID、时间和输出位置。涉及在线记录或实时回传时记录 run ID/URL、路径映射、同步器标识、轮询间隔、最后成功时间和错误。

`PREPARING` 是准备中。状态为 `RUNNING` 且日志显示真实计算进展后再报告运行。分别核验真实指标已到达在线记录器、训练日志和配置已出现在原目录并在更新、检查点按原频率保存和回传。常规核验使用有限次数的状态和日志查询，`logs --follow` 留给交互查看。

### 并行、等待与恢复

- 独立的评估、训练或数据批次可并行。有依赖的阶段按顺序，同一张卡逐个执行。多卡训练需要入口本身支持。核对同一主机上并发任务的 CPU 和内存总需求。共享资产保持不可变，资产准备需要时在同一主机内串行。
- 保存逻辑任务到平台任务 ID 的映射，先持久化一次提交结果再投递下一项。用户要求持续调度或实时回传时，复用工程控制器或建立独立运行的控制器。记录轮询间隔、重试预算与退出条件，回传在终态补齐后结束。
- 已明确拒绝的资源竞争可刷新后改用允许的候选。提交超时或结果未知时先核对平台任务和本地台账，确认未受理后再投递。路径、权限、资产校验和兼容性错误按根因处理。仅取消用户授权的任务。

### 终态回传与报告

```bash
lab results TASK_ID --output /absolute/path/to/results
lab cancel TASK_ID  # 仅在用户要求停止该任务时执行。
```

`SUCCEEDED`、`FAILED`、`CANCELED` 是终态。`UNKNOWN` 等非终态仍保留 GPU 预留。对终态补齐已产生的文件并核验原产物目录，确认记录器正常 flush/finish 和末次指标。平台归档下载适用于终态。回传失败按预算重试传输，保留远端结果。分别报告训练、在线记录和回传状态，附任务 ID、实际主机和 GPU、run 链接、日志或产物目录。持续任务说明已建立的同步机制与查看方式。

## 技能同步

本技能的仓库是 [andrewliang01/andrew-skills](https://github.com/andrewliang01/andrew-skills)，路径为 `skills/lab-gpu-dispatch/`。授权同步时提交该目录的相关改动并核对远端版本。公开源码使用 SSH 别名与本地配置，IP、个人机器上的绝对路径、密码和令牌留在本机。

上游功能对照以 [NanHaibei 的技能目录](https://github.com/NanHaibei/flowus-recording-rules/tree/main/skills/lab-gpu-dispatch) 为参考。历史验收环境见任务规格。
