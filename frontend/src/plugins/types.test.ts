import { describe, expect, it } from 'vitest'
import { pluginAsset, pluginPage, type InstalledPlugin } from './types'

const plugin: InstalledPlugin = {
  manifest: {
    id: 'demo.plugin', name: 'Demo', version: '1.0.0', apiVersion: 1,
    pages: [
      {id: 'global', title: 'Global', entry: 'ui/index.html', scope: 'global'},
      {id: 'panel', title: 'Panel', entry: 'ui/index.html'},
    ],
  },
  enabled: true,
  revision: 'a'.repeat(64),
}

describe('插件资源与页面地址', () => {
  it('资源按段编码并保留修订号缓存键', () => {
    expect(pluginAsset(plugin, 'ui/a b/star.svg')).toBe(
      './api/v1/plugins/demo.plugin/' + 'a'.repeat(64) + '/ui/a%20b/star.svg')
  })
  it('实例内页面带实例前缀，全局页面不带', () => {
    expect(pluginPage(plugin, plugin.manifest.pages![1]!, '我的 实例')).toBe(
      '/i/%E6%88%91%E7%9A%84%20%E5%AE%9E%E4%BE%8B/plugins/demo.plugin/panel')
    expect(pluginPage(plugin, plugin.manifest.pages![0]!, '我的 实例')).toBe('/plugins/demo.plugin/global')
  })
})
