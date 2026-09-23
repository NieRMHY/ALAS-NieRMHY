import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { TabSize } from './topbarPrefs'

// 模块在导入时就会往 document 上落一次档位，所以桩必须早于导入建立。
const stubs = vi.hoisted(() => {
    const values = new Map<string, string>()
    const dataset: Record<string, string> = {}
    vi.stubGlobal('localStorage', {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => { values.set(key, value) },
        removeItem: (key: string) => { values.delete(key) },
    })
    vi.stubGlobal('document', {documentElement: {dataset}})
    return {values, dataset}
})

const {cycleTabSize, readTabSize} = await import('./topbarPrefs')

beforeEach(() => {
    stubs.values.clear()
})

describe('标签页缩放的循环顺序', () => {
    it('从小到大依次走完，再从最小的重新开始', () => {
        let size: TabSize = 'xs'
        const seen: TabSize[] = [size]
        for (let i = 0; i < 5; i++) {
            size = cycleTabSize(size)
            seen.push(size)
        }
        expect(seen).toEqual(['xs', 'sm', 'md', 'lg', 'xl', 'xs'])
    })

    it('最小档之后不是跳到中间档，最大档之后回到最小', () => {
        expect(cycleTabSize('xs')).toBe('sm')
        expect(cycleTabSize('xl')).toBe('xs')
    })

    it('循环里不会出现比最小还小的档位', () => {
        let size: TabSize = 'md'
        const seen = new Set<TabSize>([size])
        for (let i = 0; i < 10; i++) {
            size = cycleTabSize(size)
            seen.add(size)
        }
        expect([...seen].sort()).toEqual(['lg', 'md', 'sm', 'xl', 'xs'])
    })

    it('落档位到 :root，顶栏高度与标签页尺寸都由它驱动', () => {
        cycleTabSize('md')
        expect(stubs.dataset.tabSize).toBe('lg')
    })

    it('没存过档位时落在中档', () => {
        expect(readTabSize()).toBe('md')
    })
})
