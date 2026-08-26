[English](#security-policy) | [繁體中文](#安全政策)

# 安全政策 / Security Policy

## 回報方式 / Reporting a Vulnerability

若你發現本專案可能存在的安全風險，請透過以下方式私密回報：

- GitHub Security Advisory（建議）：在 repo 的 **Security → Advisories** 建立 private vulnerability report
- 或聯絡維護者：將問題描述传送至 repo owner 的公開聯絡信箱（若已提供）

請提供：
- 影響版本或 commit
- 重現步驟與潛在影響
- 任何建議的修補方向

## 處理流程 / Process

- 我們將在收到後盡快確認並評估影響。
- 修補完成後會以 release 或 patch 方式發布，並在 README 說明。
- 請勿在公開 issue 中揭露 exploit 細節。

## 適用範圍 / Scope

本專案為本地端 AI 會議工具。主要風險多與模型端點設定、憑證管理與附件處理有關。若問題涉及第三方服務，建議同時向該服務回報。
