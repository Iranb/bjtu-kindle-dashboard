# Kindle RTC 唤醒与后台 Wi-Fi 实测记录

本文记录 Kindle Paperwhite 3 在固件 5.16.2.1.1 上进行的一次性深度休眠测试。
目标是确认设备能否在不显示主页、不模拟电源键的情况下，由 RTC 唤醒并短暂恢复
Wi-Fi。测试于 2026-08-10 完成。

本文只保留脱敏后的事件、状态和时间。IP 地址、MAC、序列号、SSH 用户名、无线
网络名称和凭据均未写入仓库。

## 结论

底层链路已经实测通过：

```text
正常屏保
  → readyToSuspend 最后一级
  → 设置 rtcWakeup
  → 深度休眠
  → RTC 唤醒，继续保持屏保
  → 下一轮 readyToSuspend
  → abortSuspend
  → Wi-Fi 自动恢复
  → 局域网网关可达
```

测试确认了以下事实：

- `rtcWakeup` 必须在本轮最后一个 `readyToSuspend=1` 事件之后设置；
- 过早设置的闹钟会被固件内的 Amazon 服务继续覆盖；
- RTC 唤醒不会自动退出屏保，电源状态先回到 `screenSaver`；
- `deferSuspend` 可以延长待休眠状态，但不会让已经停掉的无线接口恢复；
- 对 `com.lab126.wifid enable` 重复写入 `1` 不能恢复休眠后的射频；
- 在唤醒后的下一轮 `readyToSuspend` 调用 `abortSuspend`，会退回
  `screenSaver` 并触发正常的恢复事件；
- 这条路径中 Wi-Fi 在 1 秒内连接，默认网关可达；
- USB 线连接时设备不会进入本测试需要的深度休眠路径。

仓库现已包含基于上述机制的 `bjtu-dashboard-updater` 常驻服务。该服务与原生屏保
钩子分开安装，更新模块失败或停用时不会影响现有屏保。本文后面的“尚未验证”列表
仍是正式启用前的验收边界。

## 测试环境

| 项目 | 值 |
| --- | --- |
| 设备 | Kindle Paperwhite 3 |
| 固件 | 5.16.2.1.1 |
| 越狱组件 | Hotfix、KUAL、USBNetwork、KOReader |
| 屏保实现 | `bjtu-native-screensaver` 原生休眠钩子 |
| 连接方式 | 设备唤醒时通过 WLAN SSH 观察；测试时未连接 USB |
| RTC 测试间隔 | 180 秒 |
| Wi-Fi 判断 | `com.lab126.wifid cmState=CONNECTED` |
| 网络判断 | 默认网关单次 ICMP 检查 |

测试脚本使用独立锁和 PID 文件，结束后会删除 `/tmp` 中的一次性文件。最终测试
为了及时取回日志，在所有后台检查通过后才模拟一次电源键，使设备返回 `active`。
这次电源键事件不属于后台更新流程，正式服务不能使用它。

## 为什么早期测试没有生效

### 45 秒请求设置得太早

第一次测试在 `readyToSuspend=10` 时写入 45 秒。powerd 日志显示该请求被标记为
`rtc_set_ignored`，设备在待休眠阶段停留约 54 秒，最终写入的是系统服务已有的长
周期闹钟。

这说明很短的测试值不适合验证这条路径，也说明只看到 LIPC 写入命令成功，不代表
该值最后进入了 RTC 硬件。

### 180 秒请求被后续客户端覆盖

第二次测试仍在 `readyToSuspend=10` 时写入 180 秒。powerd 接受了请求，但随后
`phd` 在等级 8、7、6、2、1 继续登记自己的闹钟。设备真正挂起时，系统选择了
约 16 小时后的 Amazon 闹钟，而不是 180 秒请求。

因此调度器不能在第一条 `readyToSuspend` 上立刻写入。实测可用的顺序是：

```text
readyToSuspend=10
readyToSuspend=8
readyToSuspend=7
readyToSuspend=7
readyToSuspend=6
readyToSuspend=2
readyToSuspend=1
等待 2 秒
设置 rtcWakeup
```

两秒等待用于让其他等级 1 监听器先完成写入，使本项目成为本轮最后的 RTC 写入者。
这个等待值来自当前固件实测，其他固件必须重新验证。

### `deferSuspend + wifid enable` 不能恢复无线

第三次测试已经成功完成 RTC 唤醒，但采用了以下流程：

```text
readyToSuspend
  → deferSuspend 60
  → wifid enable 1
```

powerd 接受了 `deferSuspend`，设备也保持在 `readyToSuspend`，但 `cmState` 在
30 秒内一直是 `NA`。系统日志将 `enable=1` 视为重复唤醒并丢弃。直到测试退出并
模拟电源键后，powerd 才广播 `notReadyToSuspend` 和 `resuming`，无线服务随后在
约 1 秒内连接。

问题不是无线开关处于关闭状态，而是无线硬件已经随 suspend 停止，缺少正常的
powerd 恢复事件。

### USB 会改变电源状态机

USB 磁盘从 Windows 安全弹出后，Kindle 虽然能重新使用 Wi-Fi，但只要线缆仍在
供电，设备就会停在 `screenSaver`。一次 120 秒探针没有收到
`readyToSuspend`，因此不能在插线状态验证深度休眠 RTC。

## 通过测试的时间线

下面是最终一次测试的脱敏时间线，时间为设备 UTC：

| 时间 | 事件 | 状态 |
| --- | --- | --- |
| 00:35:01 | 启动一次性测试 | `active`、Wi-Fi 已连接 |
| 00:36:03 | 第一条待休眠事件 | `readyToSuspend=10` |
| 00:36:48 | 最后一条待休眠事件 | `readyToSuspend=1` |
| 00:36:50 | 写入 RTC | 目标 180 秒 |
| 00:36:57 | 真正进入挂起 | 硬件闹钟剩余 162 秒 |
| 00:39:41 | RTC 唤醒 | `screenSaver`、Wi-Fi 为 `NA` |
| 00:40:41 | 唤醒后的待休眠事件 | `readyToSuspend=10` |
| 00:40:41 | 调用 `abortSuspend` | 回到 `screenSaver` |
| 00:40:42 | 无线连接完成 | `CONNECTED` |
| 00:40:42 | 网络检查通过 | 默认网关可达 |

系统日志同时记录了：

```text
READY TO SUSPEND -> SUSPENDED
setting rtc wakeup time: secs = 162
SUSPENDED -> SCREEN SAVER
wakeup reason = POWERD_WAKEUP_REASON_RTC
READY TO SUSPEND -> SCREEN SAVER
Wi-Fi connection complete
```

`wakeupFromSuspend` 的数值参数是本次挂起时长，不应单独用作唤醒原因。正式实现
还应结合电源状态、记录的 `next-due`、`outOfScreenSaver` 和系统唤醒原因判断。

## 推荐的设备端流程

一次性验证得到的设备端顺序如下：

```text
1. goingToScreenSaver
   显示最近一次成功的面板，不等待网络。

2. 本轮 readyToSuspend 倒计时
   观察事件参数，直到 level=1。

3. 最后写入 RTC
   短暂等待其他 level=1 监听器完成，再设置 rtcWakeup。

4. wakeupFromSuspend
   确认当前仍是 screenSaver，且已达到本项目记录的 next-due。

5. 唤醒后的下一条 readyToSuspend
   调用 abortSuspend 1，使状态回到 screenSaver 并触发正常恢复事件。

6. 网络窗口
   等待 cmState=CONNECTED，再进行有超时限制的 HTTPS 拉取和校验。

7. 收尾
   清理锁和临时文件，不发送 powerButton，让 screenSaver 计时器自然进入
   下一轮挂起。
```

关键命令是：

```sh
lipc-set-prop -i com.lab126.powerd rtcWakeup "$SECONDS_FROM_NOW"
lipc-set-prop -i com.lab126.powerd abortSuspend 1
lipc-get-prop com.lab126.wifid cmState
```

正式服务不应直接写 `/sys/class/rtc/rtc0/wakealarm`，也不应通过关闭再开启无线开关
代替 powerd 恢复流程。

## 对常驻实现的要求

根据本次测试，常驻更新服务至少需要满足以下约束：

- 用事件参数识别本轮最后一级 `readyToSuspend=1`；
- RTC 写入发生在系统客户端之后，并记录实际目标 epoch；
- RTC 唤醒后仍要等待下一轮 `readyToSuspend`，不能立即调用
  `deferSuspend` 或直接操作 wifid；
- 只在确认是计划唤醒且用户没有解锁时调用 `abortSuspend`；
- `abortSuspend` 后继续保持原生屏保 shield；
- 联网、下载、校验和替换必须有统一的硬超时；
- 用户触发 `outOfScreenSaver` 时立即取消后台任务；
- 下载失败时保留旧图，并允许设备自然重新挂起；
- 每次挂起都重新参与 RTC 仲裁，不能假设上一次系统闹钟仍然有效；
- 停用服务后不再登记新的 RTC 请求。

## 已验证与待验证范围

已验证：

- 两次 180 秒 RTC 深度休眠唤醒，其中一次由常驻服务完成完整后台更新闭环；
- 唤醒原因由 powerd 记录为 RTC；
- RTC 唤醒后保持屏保状态；
- `abortSuspend` 不打开主页；
- `abortSuspend` 后 Wi-Fi 自动连接；
- 局域网默认网关可达；
- USB 连接会阻止本测试进入深度休眠；
- GitHub Contents API raw media endpoint 的 HTTPS `200` 下载和 `304` ETag；
- 1072 × 1448、8-bit 灰度 PNG 校验、SHA-256 记录、临时文件清理和原子替换；
- HTTP/TLS 失败时保留旧图，用户已处于 `active` 时取消网络窗口；
- 常驻服务没有模拟电源键，更新结束后自然再次进入深度休眠；
- USB 可见 `update.conf` 由严格白名单解析器读取，不再被特权进程 `source`。

尚未验证：

- 连续 20 次以上的周期唤醒；
- 与其他第三方 RTC 使用者同时运行时的仲裁；
- 48 小时耗电基线和电量阈值策略；
- 网络断开、DNS/TLS 失败和下载超时后的完整退避；
- 私有 endpoint 的令牌认证；
- 用户恰好在下载进行中解锁时的实机抢占时序。代码每秒检查 `active` 并终止
  子进程，但本次只实测了任务开始前已经 `active` 的取消路径。

因此，这次测试已经证明常驻服务可完成 RTC 唤醒、后台联网、条件请求、图片校验和
自然重新挂起。正式长期运行仍需连续循环、并发 RTC、下载中用户抢占和耗电验收。

## 常驻服务集成快照

2026-08-10 已把独立的 `bjtu-dashboard-updater` Upstart 服务部署到同一台设备，
并确认：

- 安装脚本能创建并启动常驻进程，原生屏保服务继续独立运行；
- 私有状态目录权限为 `0700`，`curl.conf` 权限为 `0600`；
- 所有设备端脚本均通过桌面 POSIX `sh` 和 Kindle BusyBox `sh -n` 检查；
- 本地渲染及更新器测试共 14 项，全部通过；
- `update.conf` 只接受列入白名单的键，拒绝重复键、未知键、非规范十进制、越界值、
  畸形 URL、嵌入回车和 shell 注入语法；解析失败时服务退出且不执行配置内容；
- macOS 部署器强制使用 Kindle Dropbear 支持的 legacy SCP，而不依赖 SFTP；
- `raw.githubusercontent.com` 在设备当前网络下 12 秒内没有返回数据；
- 同一仓库文件通过 GitHub Contents API 的 raw media type 返回 `200`，设备约
  10 秒取得 45,744 字节的合规 PNG，因此示例配置使用该入口；
- 首次成功请求把旧 SHA-256 原子替换为
  `f7db7aae79a21b1f3d80e3ffcbdb69180c63bedc2ef35c921dc75e2cbdb67129`，状态文件
  与实际图片一致，且没有残留 `.incoming` 文件；
- 第二次请求携带已保存的 ETag 并收到 `304`，图片哈希保持不变；
- 临时切换到不存在的 HTTPS 资源时请求失败，旧图片哈希保持不变，随后配置恢复；
- 当前网络曾连续出现 12 秒和 30 秒 TLS 连接超时，随后同一 GitHub API 地址恢复
  并成功返回。这说明单次可达验证通过，但仍必须保留超时、退避和旧图保护。

## 常驻服务完整闭环

同日又完成一次不使用 `control.sh test`、不模拟电源键的常驻服务闭环。测试前只把
`next-due` 调整到近期；设备由用户手动锁屏，之后全部由服务和固件状态机完成。
以下为设备 UTC 的脱敏时间线：

| 时间 | 事件 | 结果 |
| --- | --- | --- |
| 02:51:38 | 最后一级 `readyToSuspend=1` | 服务等待其他 RTC 客户端完成 |
| 02:51:41 | 写入 `rtcWakeup=180` | 成为本轮最后的短周期 RTC 请求 |
| 02:51:47 | 进入挂起 | `READY TO SUSPEND → SUSPENDED` |
| 02:54:29 | RTC 硬件恢复 | alarm 时间与恢复时间相同 |
| 02:54:31 | powerd 广播唤醒 | 原因为 `POWERD_WAKEUP_REASON_RTC`，状态保持屏保 |
| 02:55:32 | 下一轮待休眠 | 服务调用 `abortSuspend`，Wi-Fi 起始为 `NA` |
| 02:55:35 | Wi-Fi 恢复 | 3 次轮询后为 `CONNECTED` |
| 02:55:36 | 后台 HTTPS | Contents API 返回 `304`，ETag 生效 |
| 02:55:37 | 网络窗口结束 | `fetch_rc=0`，下次更新设为 3600 秒后 |
| 02:57:19 | 下一轮 RTC 仲裁 | 服务写入下次 RTC 请求 |
| 02:57:26 | 自然重新挂起 | `READY TO SUSPEND → SUSPENDED` |

本轮没有 `powerButton` 调用；从 RTC 恢复到更新结束期间始终是屏保状态。更新后设备
自然重新进入深度休眠，随后用户解锁才记录为外部唤醒。长周期稳定性和上述待验证
边界仍不能由单次闭环外推。
