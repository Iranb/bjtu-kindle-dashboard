# Kindle 离线优先日历锁屏

## 目标与边界

本模式不依赖常驻 Mac、Windows、41 服务器、GitHub 图片发布或 iCloud 个人日历。安装后，
Kindle 自己计算并生成锁屏：

- 公历、星期和六周月视图；
- 中国农历日期、月份与二十四节气；
- 中国法定休假日和调休工作日；
- 当天标记、非本月弱化、`休`/`班`标签。

公历、农历和节气完全离线。法定节假日由政策决定，不能从日期算法推导，因此程序同时
内置当前年度快照，并在 Wi-Fi 可用时低频获取经过严格验证的开源年度数据。网络源不可用
不会影响日期翻页。

## 数据流

```text
Kindle 本机时钟 + 内置农历算法 + 最后有效的节假日快照
  → Asia/Shanghai 六周月视图
  → 1072×1448 8-bit grayscale PNG
  → fsync + same-directory rename
  → FBInk 在 screenSaver 状态显示

可选且非阻塞：
Kindle Wi-Fi → holiday-cn HTTPS JSON → 严格验证 → root 私有缓存
```

节假日缓存只接受目标年份、最多 128 项、合法 ISO 日期、无重复日期、有限长度且无控制
字符的名称。下载、TLS、状态码、大小或结构校验失败时，继续使用内置或最后有效的数据。

## 调度

- 服务启动时离线生成一次；
- 默认每天 `00:05` 安排下一次 RTC 唤醒；
- 真实 RTC 唤醒后用 `abortSuspend` 留出本地渲染窗口；
- 本地渲染不等待 Wi-Fi，因此路由器或公网故障不会导致日期停更；
- Wi-Fi 报告 `connectionAvailable` 时，可顺带检查法定节假日数据；
- 同一设备两次成功联网检查至少间隔七天；
- 完成后不模拟电源键，由 powerd 自然重新进入深度睡眠；
- 用户解锁会取消正在运行的任务；低于 20% 电量时不安排新 RTC。

Kindle 深度睡眠期间 CPU 和 Wi-Fi 都会暂停。RTC 是让本地程序跨日运行的必要机制，但
更新的内容来自 Kindle 本身，不来自 Mac。

## 配置

默认配置：

```text
CALENDAR_MODE=offline
DAILY_REFRESH_HOUR=0
DAILY_REFRESH_MINUTE=5
HOLIDAY_REFRESH_SECONDS=604800
BATTERY_RTC_INTERVAL_SECONDS=86400
LOW_BATTERY_PERCENT=20
DISPLAY_WIDTH=1072
DISPLAY_HEIGHT=1448
DISPLAY_TIMEZONE=Asia/Shanghai
```

USB 可见配置不包含 URL、账号、密码或令牌。root 进程把配置当作白名单数据解析，拒绝
未知键、重复键、shell 字符、非规范整数和越界值。

## 失败与恢复

PNG 生成、节假日下载、JSON 校验或显示失败均不会删除当前图片。每日生成使用同目录临时
文件、`fsync` 和原子 rename；缓存损坏时自动回退到编译进程序的年度快照。

## 尚需逐台实机确认

- 新 Kindle 型号、固件、CPU 架构和 framebuffer 有效尺寸；
- jailbreak、SSH、KUAL 与 Custom Screensaver/FBInk 状态；
- 固件实际发布的 LIPC 联网/电源事件名称；
- 一次真实的锁定、RTC 唤醒、离线重绘、可选 Wi-Fi 数据检查和自然重新深睡闭环。
