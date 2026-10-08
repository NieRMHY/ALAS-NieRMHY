import {expect,type Page} from '@playwright/test'

// 官方 v2 测试密钥免图片挑战，仍需点击复选框取得新的响应 token。
export async function completeCaptcha(page:Page){
  const response=page.locator('textarea[name="g-recaptcha-response"]')
  const checkbox=page.frameLocator('iframe[title="reCAPTCHA"]').getByRole('checkbox')
  await expect(checkbox).toBeVisible({timeout:20000})
  if(!await response.inputValue())await checkbox.click()
  await expect(response).not.toHaveValue('',{timeout:20000})
  return response.inputValue()
}
