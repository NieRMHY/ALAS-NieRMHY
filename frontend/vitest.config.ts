import { defineConfig } from 'vitest/config'

// css: true 让 ?raw 导入拿到真实 CSS 源文本（默认是空串），主题契约测试据此核对三份调色板的键集合。
export default defineConfig({test: {include: ['src/**/*.test.{ts,tsx}', 'mock/**/*.test.mjs'], css: true}})
