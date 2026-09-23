const DEV_MODE_KEY = 'azurpilot.dev-mode'
const DEV_CLICK_INTERVAL_MS = 900
const DEV_CLICK_TARGET = 10

let logoClickCount = 0
let lastLogoClickAt = 0

export function readDevMode() {
  try { return window.localStorage.getItem(DEV_MODE_KEY) === '1' } catch { return false }
}

export function writeDevMode(enabled: boolean) {
  try {
    if (enabled) window.localStorage.setItem(DEV_MODE_KEY, '1')
    else window.localStorage.removeItem(DEV_MODE_KEY)
  } catch { /* 存储不可用时仅当前会话生效。 */ }
}

export function recordDevLogoClick(now = Date.now()) {
  logoClickCount = now - lastLogoClickAt <= DEV_CLICK_INTERVAL_MS ? logoClickCount + 1 : 1
  lastLogoClickAt = now
  if (logoClickCount < DEV_CLICK_TARGET) return false
  logoClickCount = 0
  lastLogoClickAt = 0
  return true
}

export function resetDevLogoClicks() {
  logoClickCount = 0
  lastLogoClickAt = 0
}
