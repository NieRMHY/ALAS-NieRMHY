/**
 * @fileoverview 检视器与全真预览共用的状态钩子：家族自定义参数，以及当前区域与两个样本层的联动。
 */

import { useEffect, useState } from 'react'
import { applyCustomLayer, type Family } from './theme'
import { readFamilyCustom, type FamilyCustom } from './themeCustom'
import type { RegionId } from './themeKnobs'

/** 家族自定义参数：切换家族时重新读取；refresh 在落盘后重新应用并刷新界面。 */
export function useFamilyCustom(family: Family) {
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const refresh = () => {
    applyCustomLayer()
    setCustom(readFamilyCustom(family))
  }
  return {custom, refresh}
}

/** 当前调节的区域与两个样本层：切到弹窗或菜单区域时自动打开对应样本，切走则一起关闭。 */
export function useSampleLayers(initial: RegionId = 'surface') {
  const [region, setRegion] = useState<RegionId>(initial)
  const [showModal, setShowModal] = useState(false)
  const [showMenu, setShowMenu] = useState(false)
  const select = (next: RegionId) => {
    setRegion(next)
    setShowModal(next === 'modal')
    setShowMenu(next === 'menu')
  }
  return {region, showModal, showMenu, select, setShowModal, setShowMenu}
}
