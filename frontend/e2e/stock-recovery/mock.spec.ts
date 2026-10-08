import {expect,test,type Page} from '@playwright/test'

const fees={commission:0,stamp:0,levy:0,borrow:0,financing:0}
const status={url:'https://fixture.invalid',instance:'demo-main',instanceId:'fixture',bindingKey:'fixture',bound:true,boundUsername:'测试玩家',authenticated:true,message:'fixture',lastObservedAt:0,snapshot:null}
const market={revision:1,serverTime:0,initialCash:2000000000,delistThreshold:0,season:{id:'2026-10',startsAt:0,endsAt:2000000000,settled:false,revenue:fees},rules:{name:'测试规则',imrPPM:500000},open:true,reason:'交易中',stocks:[],rankings:[],lifetimeRevenue:fees,participants:0}
const account={player:{id:1,username:'测试玩家'.repeat(5),identityCode:'fixture',cash:2000000000,positions:{},orders:[],watchlist:[],fees},equity:2000000000,available:2000000000,frozen:0,initialMargin:0,unsettled:0}

async function fixture(page:Page,phase:string,scope:'instance'|'all'='instance'){
  const pending:Array<()=>void>=[],requests:Array<Record<string,unknown>>=[]
  let rebuilt=false,failTransport=false,emit:()=>void=()=>{}
  await page.routeWebSocket('**/api/v1/ws',socket=>{
    const server=socket.connectToServer()
    emit=()=>{failTransport=true;socket.send(JSON.stringify({v:1,type:'event',topic:'stock',seq:1000,data:{instance:'demo-main'}}))}
    socket.onMessage(message=>{
      const request=JSON.parse(String(message)),path=request.params?.path
      const reply=(result:unknown)=>socket.send(JSON.stringify({v:1,type:'response',id:request.id,ok:true,result}))
      const error=(code:string,message:string)=>socket.send(JSON.stringify({v:1,type:'response',id:request.id,ok:false,error:{code,message}}))
      if(request.method==='stock.status'){
        if(phase==='status')pending.push(()=>reply(status))
        else if(phase==='data-error'&&!rebuilt)error('STOCK_STORAGE_DAMAGED','实例身份未登记或已删除')
        else reply(status)
      }else if(request.method==='stock.rebuild'){
        requests.push(request.params)
        rebuilt=!!request.params.confirm
        reply({instance:'demo-main',scope,affectedInstances:scope==='all'?['demo-main','demo-alt']:['demo-main'],rebuilt})
      }else if(request.method==='stock.request'){
        const data=path==='/meta'?{name:'测试交易所',mock:true,initialCash:2000000000,noticeVersion:'fixture'}:path==='/market'?market:path==='/account'?account:[]
        if(path==='/meta'&&phase==='meta-error')error('STOCK_UNAVAILABLE','模拟连接失败')
        else if(failTransport&&path==='/account')error('STOCK_IDENTITY_DAMAGED','模拟玩家身份损坏')
        else if((phase==='meta'&&path==='/meta')||(phase==='market'&&path==='/market'))pending.push(()=>reply({status:200,data,etag:'',serverTime:0}))
        else reply({status:200,data,etag:'',serverTime:0})
      }else server.send(message)
    })
    server.onMessage(message=>{
      const response=JSON.parse(String(message))
      if(phase==='schema'&&response.result?.menu)pending.push(()=>socket.send(message))
      else if(response.topic!=='stock')socket.send(message)
    })
  })
  return {pending,requests,emit:()=>emit()}
}

async function centeredReturn(page:Page){
  const link=page.getByRole('link',{name:'返回总览',exact:true})
  await expect(link).toBeVisible()
  const box=(await link.boundingBox())!,viewport=page.viewportSize()!
  expect(Math.abs(box.x+box.width/2-viewport.width/2)).toBeLessThan(2)
  expect(box.y).toBeGreaterThan(viewport.height*.2);expect(box.y).toBeLessThan(viewport.height*.9)
  expect(await link.evaluate(element=>{const rect=element.getBoundingClientRect();return element.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2))})).toBeTruthy()
}

async function topbarReturn(page:Page){
  const topbar=page.locator('.mmex-topbar'),link=topbar.getByRole('link',{name:'返回总览',exact:true}),user=topbar.getByRole('button',{name:'查看我的身份识别码'})
  await expect(link).toBeVisible();await expect(user).toBeVisible()
  const a=(await link.boundingBox())!,b=(await user.boundingBox())!
  expect(a.x+a.width).toBeLessThanOrEqual(b.x)
  expect(Math.abs(a.y+a.height/2-b.y-b.height/2)).toBeLessThan(2)
  expect(await link.evaluate(element=>{const rect=element.getBoundingClientRect();return element.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2))})).toBeTruthy()
}

for(const phase of ['schema','status','meta','market','meta-error']){
  test(`${phase} 阶段始终可从居中按钮返回总览`,async({page})=>{
    const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message))
    await fixture(page,phase)
    await page.goto('/#/i/demo-main/stock-exchange')
    if(phase==='meta-error')await expect(page.getByText('模拟连接失败',{exact:true})).toBeVisible()
    else if(['meta','market'].includes(phase))await expect(page.getByText('正在连接交易终端…',{exact:true})).toBeVisible()
    for(const viewport of [{width:1440,height:900},{width:390,height:844}]){
      await page.setViewportSize(viewport);await centeredReturn(page)
      await page.screenshot({path:`test-results/stock-${phase}-${viewport.width}.png`})
    }
    await page.getByRole('link',{name:'返回总览',exact:true}).click()
    await expect(page).toHaveURL(/#\/i\/demo-main\/overview$/)
    expect(errors).toEqual([])
  })
}

for(const scope of ['instance','all'] as const){
  test(`${scope} 玩家数据重建明确范围并在确认后恢复终端`,async({page})=>{
    const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message))
    const state=await fixture(page,'data-error',scope)
    await page.goto('/#/i/demo-main/stock-exchange')
    await expect(page.getByRole('heading',{name:'玩家数据需要处理'})).toBeVisible()
    await centeredReturn(page)
    await page.getByRole('button',{name:'完全重建账户',exact:true}).click()
    const confirmation=page.getByRole('region',{name:'确认账户重建'})
    await expect(confirmation).toContainText(scope==='all'?'所有本地交易账户':'当前实例的本地交易账户')
    const submit=page.getByRole('button',{name:'确认完全重建',exact:true})
    await expect(submit).toBeDisabled()
    expect(state.requests).toEqual([{instance:'demo-main',confirm:false,scope:'instance'}])
    await page.setViewportSize({width:390,height:844});await centeredReturn(page)
    await page.screenshot({path:`test-results/stock-rebuild-${scope}-mobile.png`})
    await page.getByLabel('我了解重建范围及后果').check();await submit.click()
    await expect(page.getByRole('heading',{name:'每一份行动力，都有价值。'})).toBeVisible()
    expect(state.requests[1]).toEqual({instance:'demo-main',confirm:true,scope})
    await topbarReturn(page)
    await page.setViewportSize({width:1440,height:900});await topbarReturn(page)
    await page.screenshot({path:`test-results/stock-rebuilt-${scope}-desktop.png`})
    expect(errors).toEqual([])
  })
}

test('进入终端后玩家身份损坏也切换到茗交所重建页面',async({page})=>{
  const state=await fixture(page,'terminal')
  await page.goto('/#/i/demo-main/stock-exchange')
  await expect(page.getByRole('heading',{name:'每一份行动力，都有价值。'})).toBeVisible()
  state.emit()
  await expect(page.getByRole('heading',{name:'玩家数据需要处理'})).toBeVisible()
  await expect(page.getByRole('button',{name:'完全重建账户',exact:true})).toBeVisible()
  await centeredReturn(page)
  await page.getByRole('link',{name:'返回总览',exact:true}).click()
  await expect(page.getByRole('button',{name:'仪表盘设置',exact:true})).toBeVisible()
})

test('顶栏返回总览在桌面和手机上位于用户名左侧且不遮挡主题按钮',async({page})=>{
  await fixture(page,'terminal')
  await page.goto('/#/i/demo-main/stock-exchange')
  await expect(page.getByRole('heading',{name:'每一份行动力，都有价值。'})).toBeVisible()
  for(const width of [1600,1200,900,780,390,320]){
    await page.setViewportSize({width,height:844});await topbarReturn(page)
    const user=page.getByRole('button',{name:'查看我的身份识别码'})
    await expect(user).toBeVisible()
    const a=(await page.getByRole('link',{name:'返回总览',exact:true}).boundingBox())!,b=(await user.boundingBox())!
    expect(a.y+a.height<=b.y||a.x+a.width<=b.x||a.x>=b.x+b.width).toBeTruthy()
    const theme=page.getByRole('button',{name:'切换到亮色主题'})
    const c=(await theme.boundingBox())!
    expect(a.y+a.height<=c.y||a.x+a.width<=c.x||a.x>=c.x+c.width,JSON.stringify({width,back:a,theme:c})).toBeTruthy()
    expect(await theme.evaluate(element=>{const rect=element.getBoundingClientRect();return element.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2))})).toBeTruthy()
    await page.screenshot({path:`test-results/stock-return-${width}.png`})
  }
})
