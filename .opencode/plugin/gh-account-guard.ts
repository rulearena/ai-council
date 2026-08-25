import type { Plugin } from "@opencode-ai/plugin"
import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

const ACCOUNT_MAP: Array<{ pattern: RegExp; account: string }> = [
  { pattern: /AIChain_Crypto/, account: "chrischiu88" },
  { pattern: /RuleArena|AI_Council/, account: "rulearena" },
]

function readActiveAccount(): string | undefined {
  try {
    const raw = readFileSync(join(homedir(), ".config/gh/hosts.yml"), "utf8")
    const match = raw.match(/^github\.com:\s*\n(?:.*\n)*?\s+user:\s*(\S+)/m)
    return match?.[1]
  } catch {
    return undefined
  }
}

function switchAccount(target: string): boolean {
  try {
    const { execSync } = require("node:child_process")
    execSync(`gh auth switch --hostname github.com --user ${target}`, {
      stdio: "pipe",
      timeout: 5000,
    })
    return true
  } catch {
    return false
  }
}

export default (async () => {
  const dirMap = new Map<string, string>()

  return {
    "shell.env": async (input, output) => {
      if (!input.callID) return
      for (const { pattern, account } of ACCOUNT_MAP) {
        if (pattern.test(input.cwd)) {
          dirMap.set(input.callID, account)
          const cur = readActiveAccount()
          if (cur !== account) {
            switchAccount(account)
          }
          return
        }
      }
    },

    "tool.execute.before": async (input, output) => {
      const target = dirMap.get(input.callID)
      dirMap.delete(input.callID)
      if (!target) return
      if (input.tool !== "bash") return
      const cmd = typeof output.args === "string" ? output.args : ""
      if (!/\bgh\b/.test(cmd)) return
      const cur = readActiveAccount()
      if (cur === target) return
      if (!switchAccount(target)) {
        throw new Error(
          `gh-account-guard: active account is ${cur ?? "unknown"}, ` +
          `this directory requires ${target}. Run: gh auth login -h github.com -u ${target}`
        )
      }
    },
  }
}) satisfies Plugin
