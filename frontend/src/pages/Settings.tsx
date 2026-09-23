import { useApp } from '../app/context'
import { ErrorBox, Loading, PageTitle } from '../components/ui'
import { DeployGroups } from '../components/DeployGroups'
import { useDeploySettings } from '../app/useDeploySettings'
import { REMOTE_ACCESS_GROUPS } from '../app/settingsGroups'

/** 系统级部署设置；外观偏好在「界面设置」，远程访问与 WebUI 在「远程访问」。 */
export function Settings() {
  const {data, error, edits, queue} = useDeploySettings()
  const {ui} = useApp()

  return (
    <>
      <PageTitle title={ui('nav.settings')} />
      {error && <ErrorBox message={error} />}
      {edits.storageError && <ErrorBox message={edits.storageError} />}
      {!data ? <Loading/> : (
        <DeployGroups data={data} except={REMOTE_ACCESS_GROUPS} edits={edits} queue={queue} />
      )}
    </>
  )
}
