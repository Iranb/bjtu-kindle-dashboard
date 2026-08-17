# Kindle 常驻屏保、联网与电源管理运维指南

本文汇总当前 Kindle HPC Dashboard 的实际部署方式、KUAL 操作、方向切换、联网
更新和电源管理策略，重点解释如何在持续供电时避免进入深度休眠。本文描述的是
仓库当前实现；早期设计文档中的试验参数若与本文冲突，以
`kindle/bjtu-dashboard-updater/update.conf.example` 和本文为准。

文档不包含设备地址、SSH 用户名、密码、无线网络名称、令牌、私钥或原始日志。

## 1. 最重要的结论

Kindle 上的“屏幕显示屏保”和“系统已经深度休眠”不是同一件事。

```text
屏幕状态：screenSaver
  ├─ 系统仍醒着：Wi-Fi 和后台进程可以运行
  └─ 系统已 suspend：Wi-Fi、SSH 和普通进程停止
```

真正 suspend 后无法继续保持 Wi-Fi 连接。当前方案采用两条互补路径：

1. **持续供电路径**：锁屏且充电时，每 30 秒续期 120 秒
   `suspendGrace`，让设备停留在 `screenSaver` 而不进入深度休眠；Wi-Fi 保持
   在线，每 5 分钟执行一次 ETag 条件请求。
2. **电池路径**：允许设备自然深度休眠；每 60 分钟由 RTC 唤醒，在屏保状态下
   调用 `abortSuspend` 恢复正常 Wi-Fi，完成受限更新窗口后自然重新深睡。

因此，“避免深度睡眠”的适用条件是：

- Kindle 持续供电；
- 用户已经锁屏，powerd 状态为 `screenSaver`；
- `bjtu-dashboard-updater` 已启用且守护进程正在运行；
- `CHARGING_KEEP_AWAKE=1`；
- powerd 能正确报告 `isCharging=1`。

它不是 connected standby，也没有修改 Kindle 的全局休眠策略。用户解锁、拔掉
电源或服务退出后，保持会在有限时间内自动释放。

## 2. 三种运行状态

| 场景 | powerd 状态 | Wi-Fi | 更新方式 | 深度休眠 |
| --- | --- | --- | --- | --- |
| 用户正在操作 | `active` | 正常 | 用户优先，后台替换取消 | 不强制 |
| 锁屏且持续供电 | `screenSaver` | 保持连接 | 每 300 秒 ETag 检查 | 通过滚动 grace 避免 |
| 锁屏且电池供电 | `suspended` / `screenSaver` | 深睡时停止 | 每 3600 秒 RTC 唤醒窗口 | 允许并主动恢复 |

用户解锁始终拥有最高优先级。收到 `outOfScreenSaver` 后，服务立即：

- 取消待执行的联网窗口；
- 把 `suspendGrace` 和 `deferSuspend` 恢复为 0；
- 不替换图片，不重新锁屏，不模拟电源键。

## 3. 当前推荐配置

以下值适用于“数据线或充电器长期供电的桌面仪表盘”：

| 配置项 | 当前值 | 作用 |
| --- | ---: | --- |
| `CHARGING_KEEP_AWAKE` | `1` | 仅在锁屏且充电时启用保持 |
| `KEEP_AWAKE_GRACE_SECONDS` | `120` | 单次 powerd 宽限时间 |
| `KEEP_AWAKE_RENEW_SECONDS` | `30` | 续期间隔及拔线检测上限 |
| `CHARGING_INTERVAL_SECONDS` | `300` | 插电状态下每 5 分钟检查 |
| `BATTERY_INTERVAL_SECONDS` | `3600` | 电池状态下每 60 分钟 RTC |
| `LOW_BATTERY_PERCENT` | `20` | 低于阈值且未充电时不安排本项目 RTC |
| `MIN_RTC_SECONDS` | `180` | RTC 测试和调度的最短间隔 |
| `RTC_FINAL_DELAY_SECONDS` | `2` | 等其他 level 1 RTC 客户端先完成 |
| `WAKE_EARLY_TOLERANCE_SECONDS` | `60` | 计划唤醒的提前容差 |
| `WIFI_CONNECT_TIMEOUT_SECONDS` | `45` | RTC 后等待 Wi-Fi 的上限 |
| `DOWNLOAD_TIMEOUT_SECONDS` | `30` | 单次 HTTPS 下载上限 |
| `NETWORK_WINDOW_TIMEOUT_SECONDS` | `60` | 后台联网窗口硬上限 |
| `MAX_IMAGE_BYTES` | `2097152` | 下载图片最大 2 MiB |
| `ALLOW_HTTP` | `0` | 生产环境只允许 HTTPS |

核心片段如下：

```text
BATTERY_INTERVAL_SECONDS=3600
CHARGING_INTERVAL_SECONDS=300
LOW_BATTERY_PERCENT=20

CHARGING_KEEP_AWAKE=1
KEEP_AWAKE_GRACE_SECONDS=120
KEEP_AWAKE_RENEW_SECONDS=30

MIN_RTC_SECONDS=180
RTC_FINAL_DELAY_SECONDS=2
WAKE_EARLY_TOLERANCE_SECONDS=60

WIFI_CONNECT_TIMEOUT_SECONDS=45
DOWNLOAD_TIMEOUT_SECONDS=30
NETWORK_WINDOW_TIMEOUT_SECONDS=60
MAX_IMAGE_BYTES=2097152
ALLOW_HTTP=0
```

不要把 grace 设置成数小时或永久值。`120/30` 的组合保留了四次续期间隔的余量，
同时保证守护进程崩溃后最长约 120 秒自然失效，拔线后下一次 30 秒 tick 即可释放。

## 4. 持续供电时如何避免深度休眠

守护进程每 30 秒执行一次判断：

```text
CHARGING_KEEP_AWAKE == 1
  AND isCharging == 1
  AND power_state == screenSaver
```

三项同时成立时执行：

```sh
lipc-set-prop -i com.lab126.powerd suspendGrace 120
lipc-set-prop -i com.lab126.powerd deferSuspend 120
```

其中 `suspendGrace` 是目标固件上已经确认有效的保持手段；`deferSuspend` 只是第二
道保护，因为部分固件仅在 `readyToSuspend` 阶段处理它。服务不会使用
`preventScreenSaver`，因为那会破坏锁屏仪表盘语义。

在该状态下：

```text
screenSaver + charging
  → 每 30 秒续期 120 秒 suspendGrace
  → Wi-Fi 保持 CONNECTED
  → 每 300 秒发起 HTTPS If-None-Match
  → 304：不写图片，不刷新墨水屏
  → 200：完整校验后原子替换，有变化才 GC16
```

四种自动释放条件：

| 条件 | 释放行为 |
| --- | --- |
| 用户解锁 | 同一事件周期把两个 grace 值清零并取消后台任务 |
| 断开供电 | 下一次 30 秒 tick 检出，释放后回到电池 RTC 路径 |
| 守护进程退出 | 最后一次 120 秒 grace 自然到期 |
| 配置关闭保持 | 重启服务后不再续期，已有 grace 自然到期 |

### 不应采用的做法

- 不要声称 Wi-Fi 能在真正的 suspend 中保持连接；
- 不要循环写 `wifid enable=1`，它不能恢复已经停掉的射频；
- 不要用 `powerButton` 模拟用户唤醒；
- 不要把 `preventScreenSaver` 当作常驻锁屏方案；
- 不要直接写 `/sys/class/rtc/rtc0/wakealarm` 绕过 powerd；
- 不要把 grace 设置成永久值或远大于 watchdog 的值；
- 不要为了测试 RTC 而在 USB 持续供电状态下等待深睡，因为外部供电会改变状态机。

## 5. 断电后的 RTC 深睡回退

电池供电时，设备允许正常 suspend。深睡期间 Wi-Fi、SSH 和更新脚本均不运行。
服务通过 powerd 事件完成以下闭环：

```text
用户手动锁屏
  → readyToSuspend 的最后 level=1
  → 等待 2 秒，让系统 RTC 客户端完成写入
  → 设置一次性 rtcWakeup
  → 自然进入深度休眠
  → RTC 恢复，仍停留在 screenSaver
  → 等待唤醒后的下一轮 readyToSuspend
  → abortSuspend 1
  → powerd 广播正常恢复事件
  → Wi-Fi 重新连接
  → HTTPS/ETag/图片校验/可选渲染
  → 不发送电源键，让设备自然重新深睡
```

`rtcWakeup` 不能在第一条 `readyToSuspend` 就写入。目标固件上的 Amazon 客户端会
在等级 10、8、7、6、2、1 继续改写硬件闹钟；当前服务只在最后的 level 1 后再
延迟 2 秒写入。

RTC 唤醒后也不能立即反复启用 Wi-Fi。实测可行的恢复点是唤醒后的下一轮
`readyToSuspend`，此时调用：

```sh
lipc-set-prop -i com.lab126.powerd abortSuspend 1
```

这样 powerd 回到 `screenSaver`，不会打开主页，并触发无线硬件的正常恢复事件。

## 6. 更新与旧图保护

每次下载都遵循同一安全顺序：

1. 读取并严格校验当前方向对应的 ETag；
2. 通过 HTTPS 发送 `If-None-Match`；
3. `304` 只更新成功状态，不触碰图片和墨水屏；
4. `200` 先写到同目录 `.incoming`；
5. 校验响应类型、大小和 PNG 签名；
6. 校验分辨率为 1072 × 1448、bit depth 为 8、颜色类型为灰度 0；
7. 计算 SHA-256，与当前面板比较；
8. 内容相同则不渲染；内容变化才通过同文件系统 `mv` 原子替换；
9. 仅在替换成功后写入 ETag、哈希和成功时间；
10. TLS、网络、超时或内容校验失败时保留最后一张完整图片。

失败退避默认为 1、2、4 小时，最大 6 小时。更新器不会因为远端暂时不可用而清空
屏幕或覆盖旧图。

## 7. KUAL 日常操作

首次部署后必须同时存在：

```text
/mnt/us/extensions/bjtu-dashboard-updater/config.xml
/mnt/us/extensions/bjtu-dashboard-updater/menu.json
```

`config.xml` 是 KUAL 的注册清单。复制新扩展后退出并重新打开 KUAL，才能重新扫描
扩展目录。

进入 `BJTU Dashboard Updater` 后可使用：

| 按钮 | 作用 |
| --- | --- |
| `Enable scheduled updates` | 启用并启动常驻更新器 |
| `Disable scheduled updates` | 停止调度但保留最后屏保 |
| `Restart updater` | 修改配置后重新加载 |
| `Fetch panel now` | 设备醒着时立即执行一次受保护拉取 |
| `Toggle portrait / right 90 degrees` | 在竖屏和右转横屏间切换 |
| `Display: portrait` | 明确切到竖屏 |
| `Display: right 90 degrees` | 明确切到顺时针右转 90° |
| `Updater status` | 查看脱敏运行状态 |
| `Uninstall updater` | 移除调度服务并恢复原渲染钩子 |

方向切换会短暂停止更新器，强制下载该方向的图片，校验并原子替换后再恢复调度。
下载失败时，root 私有的“当前实际方向”不会前进。

## 8. SSH 运维命令

以下示例使用本机私有 SSH alias `kindle`，不要把真实地址或凭据写进仓库：

```sh
ssh kindle '/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh status'
ssh kindle '/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh fetch-now'
ssh kindle '/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh restart'
ssh kindle '/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh orientation toggle'
ssh kindle '/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh orientation portrait'
ssh kindle '/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh orientation right'
ssh kindle '/mnt/us/extensions/bjtu-dashboard-updater/bin/control.sh disable'
```

安全的只读电源诊断：

```sh
ssh kindle 'lipc-get-prop com.lab126.powerd state'
ssh kindle 'lipc-get-prop com.lab126.powerd isCharging'
ssh kindle 'lipc-get-prop com.lab126.powerd suspendGrace'
ssh kindle 'lipc-get-prop com.lab126.wifid cmState'
```

期望的插电锁屏状态是：

```text
state=screenSaver
isCharging=1
suspendGrace 接近 120，并被周期续期
cmState=CONNECTED
```

不要把完整 `update.conf`、`curl.conf`、证书信息或原始服务日志粘贴到 issue、PR
或公开聊天中。

## 9. 配置与权限边界

USB 可见的 `update.conf` 只能包含公开 URL 和白名单设置。特权进程不会 `source`
或 `eval` 它；重复键、未知键、shell 语法、非规范十进制、越界值和畸形 URL 都会
导致服务拒绝启动。

私有 TLS 选项放在：

```text
/var/local/bjtu-dashboard/curl.conf        mode 0600
/var/local/bjtu-dashboard/edge-ca.pem      仅 CA 公钥证书
```

私钥、密码、令牌和环境地址不得进入 USB 配置、日志、Git、文档或 PR。生产环境保持
`ALLOW_HTTP=0`，不得使用 `curl --insecure`。

## 10. 屏幕方向与时间

- `portrait`：正常竖屏；原生钩子叠加时间、日期和电量；
- `right`：Kindle 实体顺时针右转 90°；下载预先逆时针旋转的原生尺寸图片；
- 不旋转 framebuffer，不改变 Kindle 系统 UI 和触摸坐标；
- 当前不支持左转 90°或倒置；
- 竖屏时间显式使用 POSIX `TZ=CST-8`，即 UTC+8，不依赖 Kindle 系统时区；
- 右转模式不叠加竖屏坐标的实时时间和电量。

## 11. 常见故障

### KUAL 看不到 Updater

确认扩展目录同时包含 `config.xml` 和 `menu.json`，然后完全退出并重新打开 KUAL。
只有 `menu.json` 时，当前 KUAL 会忽略整个目录。

### 插电锁屏后仍进入深睡

依次确认：

1. `control.sh status` 显示服务运行；
2. `CHARGING_KEEP_AWAKE=1`；
3. powerd 的 `isCharging=1`；
4. 状态为 `screenSaver` 而不是 `active`；
5. `KEEP_AWAKE_RENEW_SECONDS` 小于 `KEEP_AWAKE_GRACE_SECONDS`；
6. 修改配置后已经执行 `Restart updater`。

### 屏保一直是旧数据

先在设备醒着时执行 `Fetch panel now`。`304` 表示远端语义未变化，不是失败；若
下载失败，旧图保留是预期行为。继续检查 Mac 发布器、HTTPS edge 和证书信任，
不要降低 TLS 安全级别。

### 深睡唤醒后 Wi-Fi 是 `NA`

RTC 刚恢复时出现 `NA` 是正常的。服务需要等下一轮 `readyToSuspend` 并调用
`abortSuspend`，随后再等待最多 45 秒。不要用重复写 `wifid enable=1` 代替。

### 竖屏时间慢 8 小时

确认安装的 `render-panel.sh` 包含 `LOCKSCREEN_TZ="CST-8"`。不要修改 Kindle
系统时钟来修复锁屏显示时区。

## 12. 已验证范围

目标设备为 Kindle Paperwhite 3，固件 5.16.2.1.1。当前已经实测：

- 两次 180 秒 RTC 深度休眠唤醒；
- 一次常驻服务完整闭环：RTC、`abortSuspend`、Wi-Fi、HTTPS `304`、自然重睡；
- 后续 6 轮连续计划 RTC 唤醒和条件请求；
- RTC 恢复期间始终停留在屏保，没有模拟电源键；
- 插电锁屏状态持续为 `screenSaver`、Wi-Fi 为 `CONNECTED`；
- 连续两次 5 分钟 ETag `304`，图片哈希不变且没有渲染；
- 用户解锁同一秒释放 grace，powerd 的相关值恢复为 0；
- HTTPS `200/304`、PNG 尺寸与灰度、SHA-256、原子替换和失败保留旧图；
- 竖屏 UTC+8 时间；
- 竖屏与右转模式实机往返；
- KUAL 注册和方向切换按钮可见。

## 13. 尚未验证的边界

以下内容不得写成已经完成：

- 物理拔线后 30 秒内从保持模式切换到 RTC 模式的完整实机时间线；
- 插电保持模式连续 12–24 小时稳定性；
- 电池模式连续 20 轮和 48 小时耗电基线；
- 与其他第三方 RTC 扩展同时运行时的仲裁；
- 用户恰好在下载进行中解锁的完整实机抢占时序；
- 所有 DNS、TLS、断网和超时组合下的完整退避序列；
- 其他 Kindle 型号和固件上的 `suspendGrace`、RTC 与 `abortSuspend` 行为；
- 左转 90°和倒置布局。

固件、网络、edge 身份、CA、休眠钩子或更新脚本发生变化后，应重新验证受影响的
最小层，并至少再完成一次真实 RTC 闭环。

## 14. 推荐验收清单

### 插电保持模式

1. 启用更新器并手动锁屏；
2. 确认 `screenSaver + isCharging=1`；
3. 连续观察 `suspendGrace` 被 30 秒 tick 续期；
4. 确认 Wi-Fi 始终为 `CONNECTED`；
5. 观察两次完整 300 秒 ETag 周期；
6. `304` 时确认图片 mtime、SHA-256 和屏幕均不变；
7. 用户解锁，确认同一事件周期释放 grace；
8. 单独进行拔线回退和长时间稳定性测试。

### 电池 RTC 模式

1. 断开外部供电；
2. 把下一次更新安排到不短于 180 秒的未来；
3. 由用户手动锁屏，测试期间保持锁定；
4. 确认最后 level 1 后才写入 RTC；
5. 确认唤醒原因为 RTC，画面仍是屏保；
6. 确认下一轮待休眠时调用 `abortSuspend`；
7. 确认 Wi-Fi、HTTPS 和图片校验结果；
8. 不发送电源键，确认设备自然重新进入深度休眠；
9. 完成记录后再由用户解锁。

生产服务没有模拟电源键的测试入口，也不应重新加入这种入口。
