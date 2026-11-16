/**
 * @fileoverview 插件主导航视图：把全局页面、实例内页面与插件页面汇总给插件导航实现。
 */
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../app/context'
import { PluginFrame } from './PluginFrame'
import { usePlugins } from './context'
import { pluginPage } from './types'

/** 导航替换视图的宿主参数；fallback 为未启用插件导航时的内置导航。 */
export interface PluginNavigationProps {
  /** 当前实例名；全局导航为 undefined。 */
  instance?: string
  /** 点击导航后的收尾动作，例如关闭移动端抽屉。 */
  onNavigate?: () => void
  /** 没有插件导航视图时渲染的内置导航。 */
  fallback: ReactNode
}

/**
 * 插件导航视图：不可用时回落传入的 fallback（内置主导航）。
 * 插件只能打开 items 中列出的地址，宿主不暴露任意跳转能力。
 */
export function PluginNavigation({instance, onNavigate, fallback}: PluginNavigationProps) {
  const {ui} = useApp()
  const {theme, plugins} = usePlugins()
  const navigate = useNavigate()
  const entry = theme?.manifest.theme?.navigationView
  if (!theme || !entry) return <>{fallback}</>
  const base = instance ? '/i/' + encodeURIComponent(instance) : ''
  const items = instance ? [
    {title: ui('nav.overview'), to: base + '/overview'},
    {title: ui('nav.resources'), to: base + '/resources'},
    {title: ui('nav.statistics'), to: base + '/statistics'},
    ...plugins.filter(plugin => plugin.enabled).flatMap(plugin =>
      plugin.manifest.pages?.filter(page => (page.scope !== 'global') === Boolean(instance)).map(page =>
        ({title: page.title, to: pluginPage(plugin, page, instance)})) ?? []),
  ] : [
    {title: ui('nav.home'), to: '/'},
    {title: ui('nav.updater'), to: '/updater'},
    {title: ui('nav.interface'), to: '/interface'},
    {title: ui('nav.plugins'), to: '/plugins'},
    {title: ui('nav.remote'), to: '/remote'},
    {title: ui('nav.configs'), to: '/configs'},
    {title: ui('nav.settings'), to: '/settings'},
    {title: ui('nav.developer'), to: '/dev'},
    ...plugins.filter(plugin => plugin.enabled).flatMap(plugin =>
      plugin.manifest.pages?.filter(page => page.scope === 'global').map(page =>
        ({title: page.title, to: pluginPage(plugin, page, instance)})) ?? []),
  ]
  return <div className="apu-navigation" data-apu-component="navigation">
    <PluginFrame key={theme.revision + ':' + instance} plugin={theme} entry={entry}
      title={ui('nav.primary')} instance={instance} fallback={fallback}
      navigation={{items, go: to => {onNavigate?.(); navigate(to)}}}/>
  </div>
}
