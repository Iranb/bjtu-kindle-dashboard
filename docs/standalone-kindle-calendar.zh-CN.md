# Kindle 自主日历锁屏

## 目标与边界

本模式不依赖 Mac、Windows、41 服务器或 GitHub 发布图片。Kindle 只依赖 Wi-Fi 和日历
提供方：它直接拉取只读 ICS，然后在本机生成锁屏图。

Apple 的 EventKit 只存在于 Apple 设备上，Kindle 无法直接读取私有的 Calendar.app 数据库。
无 Mac 常驻参与时，可行入口是 iCloud 的只读公共日历链接。拿到链接的人可以读取该日历，
因此建议专门新建一个用于 Kindle 的日历，只放适合显示在锁屏上的日程；不应公开主日历。

## 数据流

```text
iCloud public calendar (HTTPS ICS)
  → Kindle Wi-Fi / RTC network window
  → conditional GET (ETag + Last-Modified)
  → 4 MiB 上限、VCALENDAR/VEVENT 严格解析
  → Asia/Shanghai 月视图与重复日程展开
  → 1072×1448 8-bit grayscale PNG
  → fsync + same-directory rename
  → FBInk 在 screenSaver 状态显示
```

解析器只保留 UID、标题、起止时间、全天标记和重复规则。地点、备注、参与人、组织者与
账户信息不会进入渲染模型。标题会出现在最终 PNG 中，这是锁屏功能本身所必需的隐私暴露。

## 调度

- Wi-Fi 报告 `connectionAvailable` 时立即刷新；
- 正常联网时默认 15 分钟检查一次；
- 电池模式下在 `readyToSuspend` 阶段设置 RTC，默认 1 小时；
- 真实 RTC 唤醒后仅在计划时间窗口使用 `abortSuspend`，等待 Wi-Fi 并更新；
- 不使用模拟电源键，不强制保持 Wi-Fi 在深度睡眠中连接；
- 用户解锁会取消正在运行的更新；低于 20% 电量时不设置新的 RTC 唤醒。

Kindle 深度睡眠时 CPU 和 Wi-Fi 都会暂停，因此“每 15 分钟检查”只适用于设备当前有运行
窗口的情况；深睡时的真实刷新粒度由 1 小时 RTC 周期决定。两项都可在严格白名单配置中
调整，但不建议把 RTC 周期设得过短。

## 失败与恢复

订阅文件权限过宽、非 HTTPS、TLS 验证失败、超时、响应过大、ICS 语法错误、重复规则异常、
PNG 生成失败或用户解锁，均不会替换当前锁屏。更新使用同目录临时文件、`fsync` 和原子
rename；HTTP 304 仍会用缓存 ICS 重新生成图片，使“今天”标记能够跨日更新。

## 尚需逐台实机确认

- 新 Kindle 的型号、固件、CPU 架构与 framebuffer 有效尺寸；
- jailbreak、SSH、KUAL、MRPI/KPM 与 FBInk/屏保 shield 的安装状态；
- 该固件实际发布的 LIPC 联网/电源事件名称；
- iCloud HTTPS 的根证书链是否被设备信任；必要时仅把明确的 CA bundle 以 `0600` 放入
  `/var/local/kindle-calendar/ca.pem`，绝不关闭校验；
- 一次真实的锁定、RTC 唤醒、Wi-Fi 恢复、更新、自然重新深睡闭环。
