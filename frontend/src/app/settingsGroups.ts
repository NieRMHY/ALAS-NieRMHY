/**
 * 部署设置分组的页面归属。
 *
 * 与 `module/runtime/deploy_settings.py` 的 `DEPLOY_GROUPS` 对应：这里只登记
 * 被专门页面认领的分组，「系统设置」渲染剩下的一切，后端新增分组时不会在
 * 界面上静默消失。
 */
export const REMOTE_ACCESS_GROUPS = ['RemoteAccess', 'Webui']
