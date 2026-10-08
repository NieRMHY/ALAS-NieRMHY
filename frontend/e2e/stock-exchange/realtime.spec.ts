import {expect,test,type Page} from '@playwright/test'
import {createHash,generateKeyPairSync,randomUUID,sign} from 'node:crypto'
import {completeCaptcha} from './recaptcha'

async function listedPlayer(page:Page,name:string,actionPoints:number){
  const {privateKey,publicKey}=generateKeyPairSync('ed25519'),instanceId=randomUUID(),pub=publicKey.export({type:'spki',format:'der'}).subarray(-32).toString('base64'),key=createHash('sha256').update(pub+'\n'+instanceId).digest('hex')
  const observedAt=Math.floor(Date.now()/1000)
  const report=(ap:number,observed:number)=>{const issuedAt=Math.floor(Date.now()/1000),value={instanceId,publicKey:pub,actionPoints:ap,observedAt:observed,issuedAt,signature:''};value.signature=sign(null,Buffer.from(`mmex-instance-v1\n${instanceId}\n${pub}\n${ap}\n${observed}\n${issuedAt}\n`),privateKey).toString('base64');return value}
  const response=await page.request.post('http://127.0.0.1:8088/api/register',{data:{username:name,password:'fixture-test-password',acceptedNotice:'2026-10-03',recaptchaToken:'recaptcha-test-token',report:report(actionPoints,observedAt)}})
  expect(response.ok()).toBeTruthy();const player=await response.json()
  return {name,id:player.player.id,async quote(ap:number,offset=1){const response=await page.request.post('http://127.0.0.1:8088/api/quotes',{headers:{Authorization:`Bearer ${player.uploadToken}`,'X-MMEX-Instance':key},data:{report:report(ap,observedAt+offset)}});expect(response.ok()).toBeTruthy()}}
}

async function unobstructed(page:Page,selector:string){
  await expect.poll(()=>page.locator(selector).evaluate(element=>{const rect=element.getBoundingClientRect(),x=rect.x+rect.width/2,y=rect.y+rect.height/2;return x>=0&&y>=0&&x<innerWidth&&y<innerHeight&&element.contains(document.elementFromPoint(x,y))})).toBeTruthy()
}

test('自选持久化、默认退市过滤、实时总浮盈亏和多分辨率弹窗按钮',async({page})=>{
  test.setTimeout(120000)
  const suffix=String(Date.now()),errors:string[]=[];page.on('pageerror',error=>errors.push(error.message))
  const [long,short,delisted]=await Promise.all([listedPlayer(page,'实时多头'+suffix,1000),listedPlayer(page,'实时空头'+suffix,1500),listedPlayer(page,'退市'+suffix,0)])
  await page.goto('/#/')
  await expect(page.getByRole('button',{name:'新建实例',exact:true})).toBeVisible()
  const instance='实时实例'+suffix
  await page.evaluate(async name=>{const {api}=await import('/src/api/client.ts');await api.request('instances.create',{name,source:'demo-main'})},instance)
  await page.goto(`/#/i/${encodeURIComponent(instance)}/stock-exchange`)
  const auth=page.getByRole('dialog',{name:'开通交易账户'})
  await expect(auth).toBeVisible();await auth.getByLabel('唯一用户名').fill('实时交易'+suffix);await auth.getByLabel('密码',{exact:true}).fill('strong-test-password');await auth.getByLabel('我已阅读注意事项').check();await completeCaptcha(page)
  for(const viewport of [{width:320,height:240},{width:390,height:844},{width:640,height:320},{width:1280,height:720}]){await page.setViewportSize(viewport);await unobstructed(page,'.auth-dialog .modal-actions button');await unobstructed(page,'.auth-dialog .overview-link')}
  await auth.getByRole('button',{name:'验证并开通交易账户'}).click();await expect(auth).not.toBeVisible({timeout:20000})
  const securities=page.locator('.watchlist')
  await expect(securities.locator('.stock-row').filter({hasText:delisted.name})).toHaveCount(0)
  await securities.getByRole('button',{name:'添加自选股 '+long.name,exact:true}).click()
  await securities.getByRole('button',{name:/^自选股/}).click();await expect(securities.locator('.stock-row')).toHaveCount(1)
  await page.reload();await expect(securities.getByRole('button',{name:'移除自选股 '+long.name,exact:true})).toHaveAttribute('aria-pressed','true')
  await securities.locator('summary').click();await securities.getByLabel('上市状态').selectOption('all');await securities.getByLabel('搜索证券').fill(delisted.name);await expect(securities.locator('.stock-row')).toHaveCount(1)
  await securities.getByRole('button',{name:'重置过滤器'}).click();await expect(securities.locator('.stock-row').filter({hasText:delisted.name})).toHaveCount(0)
  await securities.locator('.stock-row').filter({hasText:long.name}).click()
  const ticket=page.locator('.ticket')
  await ticket.getByLabel('委托数量').fill('2');await ticket.getByRole('button',{name:'提交买入委托'}).click()
  for(const viewport of [{width:320,height:240},{width:640,height:320},{width:390,height:844},{width:1600,height:1080}]){await page.setViewportSize(viewport);await unobstructed(page,'.review-dialog .modal-close');await unobstructed(page,'.review-dialog .modal-actions button')}
  await page.screenshot({path:'test-results/realtime-confirm-desktop.png',fullPage:true})
  await page.getByRole('dialog',{name:'确认交易委托'}).getByRole('button',{name:'确认提交'}).click();await expect(page.getByRole('dialog',{name:'确认交易委托'})).not.toBeVisible()
  await securities.locator('.stock-row').filter({hasText:short.name}).click();await ticket.getByRole('button',{name:'卖空',exact:true}).click();await ticket.getByLabel('委托数量').fill('3');await ticket.getByRole('button',{name:'提交卖空委托'}).click();await page.getByRole('dialog',{name:'确认交易委托'}).getByRole('button',{name:'确认提交'}).click();await expect(page.getByRole('dialog',{name:'确认交易委托'})).not.toBeVisible()
  await Promise.all([long.quote(1100),short.quote(1400)])
  await page.locator('.mmex-sidebar').getByRole('button',{name:'我的持仓',exact:true}).click()
  await unobstructed(page,'.mmex-section-heading h1')
  await expect(page.locator('.portfolio-summary>div').first()).toContainText('+490.00',{timeout:4000})
  await long.quote(1200,2);await expect(page.locator('.portfolio-summary>div').first()).toContainText('+690.00',{timeout:4000})
  await page.screenshot({path:'test-results/realtime-portfolio-desktop.png',fullPage:true})
  await page.getByRole('button',{name:'查看我的身份识别码'}).click()
  for(const viewport of [{width:320,height:240},{width:640,height:320},{width:390,height:844}]){await page.setViewportSize(viewport);await unobstructed(page,'.identity-dialog .modal-close');await unobstructed(page,'.identity-dialog .modal-actions button');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()}
  await page.screenshot({path:'test-results/realtime-identity-mobile.png',fullPage:true});await page.getByRole('button',{name:'关闭身份信息'}).click()
  expect(errors).toEqual([])
})
