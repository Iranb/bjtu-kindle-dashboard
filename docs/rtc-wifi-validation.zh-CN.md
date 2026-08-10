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

- 一次 180 秒 RTC 深度休眠唤醒；
- 唤醒原因由 powerd 记录为 RTC；
- RTC 唤醒后保持屏保状态；
- `abortSuspend` 不打开主页；
- `abortSuspend` 后 Wi-Fi 自动连接；
- 局域网默认网关可达；
- USB 连接会阻止本测试进入深度休眠；
- 失败路径能保留现有原生屏保服务。

尚未验证：

- 后台 HTTPS 下载、ETag、令牌和图片原子替换；
- 不使用测试清理电源键时的自动再次挂起；
- 连续 20 次以上的周期唤醒；
- 与其他第三方 RTC 使用者同时运行时的仲裁；
- 48 小时耗电基线和电量阈值策略；
- 网络断开、DNS/TLS 失败和下载超时后的完整退避；
- 用户恰好在后台更新窗口内解锁时的抢占处理。

因此，这次测试证明了 RTC 唤醒和后台联网的底层路径可行。仓库中的常驻服务已经
实现 HTTPS 拉取和失败保护；部署后仍需验证无测试清理动作的自然重新挂起，再进行
连续循环和耗电测试。
