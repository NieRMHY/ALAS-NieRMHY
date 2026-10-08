/**
 * @fileoverview 旧版实例页右列内容（目录或调度器）偏好管理。
 */

import { prefStore } from './prefStore'

/**
 * 旧版实例页右列显示什么。
 *
 * `directory` —— 默认。任务设置页的锚点目录，点一下滚到对应的参数分组。
 * `scheduler` —— 调度器与任务计划，与新版右栏同一套内容。
 *
 * 与其它界面偏好一张存法：关掉再打开接着上次的样子，直到用户自己切回去。
 */
export type RailView = 'directory' | 'scheduler'

const store = prefStore<RailView>('azurpilot.legacy-rail-view', raw => raw === 'scheduler' ? 'scheduler' : 'directory')

export const readRailView = store.read
export const subscribeRailView = store.subscribe
export const setRailView = store.write
