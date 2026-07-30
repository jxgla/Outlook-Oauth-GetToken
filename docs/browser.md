# 浏览器隔离与后台运行

Outlook-Oauth-GetToken 启动本机 Chrome 时默认加入 `--guest` 与 `--incognito`，配合 DrissionPage 的临时用户目录和退出时 `del_data=True` 清理，尽量避免本机 Chrome / Windows / Microsoft 登录态或历史 cookie 被带入 OAuth 冷登录流程。

## 配置

```jsonc
"headless": false,
"browser": {
  "background": false
}
```

- `headless=false`：显示真实 Chrome 窗口。
- `browser.background=true`：仅在有头模式下生效，启动并准备好 tab 后将窗口最小化挂后台，减少抢占前台和干扰正常工作。
- `headless=true`：无窗口运行，`browser.background` 不再额外生效。

## 行为边界

- guest/incognito 是启动参数，默认开启，不单独提供开关。
- 后台运行只做窗口最小化，不改变 headful Chrome 本质。
- 退出时仍由主流程调用 `browser.quit(timeout=5, force=True, del_data=True)` 清理临时数据。