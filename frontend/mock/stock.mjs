import {createHash,createPrivateKey,createPublicKey,sign} from 'node:crypto'
import {mkdirSync,readFileSync,writeFileSync,renameSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {join} from 'node:path'

// Mock 同样使用 Go 交易引擎和 Cloudflare 官方测试验证码；实例资源来自本地夹具。
export function createStockProxy(snapshot){
  const instances=new Map()
  const generations=new Map()
  const listeners=new Set()
  let streamController=null,streamRunning=false
  const url=(process.env.STOCK_EXCHANGE_URL??'http://127.0.0.1:8080').replace(/\/$/,'')
  const target=new URL(url)
  if(!['127.0.0.1','localhost','[::1]'].includes(target.hostname))throw new Error('交易所 Mock 只能连接本机回环服务')
  async function listen(){
    if(streamRunning)return;streamRunning=true
    try{while(listeners.size){
      streamController=new AbortController()
      try{
        const response=await fetch(url+'/api/events',{signal:streamController.signal})
        if(!response.ok||!response.headers.get('Content-Type')?.includes('text/event-stream'))throw new Error('事件流不可用')
        const reader=response.body.getReader(),decoder=new TextDecoder();let buffer=''
        while(listeners.size){const {value,done}=await reader.read();if(done)throw new Error('事件流中断');buffer+=decoder.decode(value,{stream:true})
          let newline;while((newline=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,newline);buffer=buffer.slice(newline+1);if(line.startsWith('data: ')){const data=JSON.parse(line.slice(6));listeners.forEach(listener=>listener({...data,online:true}))}}
        }
      }catch{if(listeners.size){listeners.forEach(listener=>listener({online:false}));await new Promise(resolve=>{const retry=setTimeout(resolve,1000);retry.unref()})}}
      finally{streamController?.abort();streamController=null}
    }}finally{streamRunning=false;if(listeners.size)void listen()}
  }
  function identity(name){
    if(!instances.has(name)){
      // 固定 Mock 身份使演示服务重启后仍能登录 Go 中永久绑定的账户。
      const generation=generations.get(name)??0
      const seed=createHash('sha256').update(`mmex-mock-identity-v1\n${process.env.AZURPILOT_MOCK_STOCK_NAMESPACE??'local-demo'}\n${name}${generation?'\nrebuild-'+generation:''}`).digest()
      const privateKey=createPrivateKey({key:Buffer.concat([Buffer.from('302e020100300506032b657004220420','hex'),seed]),type:'pkcs8',format:'der'}),publicKey=createPublicKey(privateKey)
      const h=createHash('sha256').update(seed).digest('hex'),id=`${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20,32)}`
      const pub=publicKey.export({type:'spki',format:'der'}).subarray(-32).toString('base64')
      const directory=fileURLToPath(new URL('../../config/stock-exchange/mock-history/',import.meta.url)),path=join(directory,h+'.json')
      let rows=[];try{rows=JSON.parse(readFileSync(path,'utf8'))}catch{}
      const history=new Map(rows.filter(r=>Number.isSafeInteger(r.time)&&Number.isSafeInteger(r.actionPoints)&&r.actionPoints>=0&&r.actionPoints<=1000000).map(r=>[r.time,r]))
      instances.set(name,{id,pub,privateKey,key:createHash('sha256').update(pub+'\n'+id).digest('hex'),token:'',upload:'',player:null,history,pending:new Set(history.keys()),directory,path,busy:false,next:0,checked:0})
    }
    return instances.get(name)
  }
  function report(name){
    const i=identity(name),row=snapshot(name),now=Math.floor(Date.now()/1000)
    const result={instanceId:i.id,publicKey:i.pub,actionPoints:row?.actionPoints??0,observedAt:row?.observedAt??now,issuedAt:now}
    result.signature=sign(null,Buffer.from(`mmex-instance-v1\n${i.id}\n${i.pub}\n${result.actionPoints}\n${result.observedAt}\n${now}\n`),i.privateKey).toString('base64')
    return result
  }
  async function remote(path,method='GET',body=null,token='',binding='',etag=''){
    const headers={'Content-Type':'application/json'}
    if(token)headers.Authorization='Bearer '+token
    if(binding)headers['X-MMEX-Instance']=binding
    if(etag)headers['If-None-Match']=etag
    let response
    try{
      response=await fetch(url+'/api'+path,{method,headers,body:body===null?undefined:JSON.stringify(body),signal:AbortSignal.timeout(12000)})
    }catch{
      // 上游断网不是浏览器请求格式错误；保留交易代理的错误语义和联合 Mock 启动提示。
      throw Object.assign(new Error(`无法连接本机交易所 Mock（${url}）。请先在 AzurPilot_StockExchange 启动 npm run dev:mock --prefix frontend，再重试连接。`),{code:'STOCK_UNAVAILABLE'})
    }
    try{
      const data=response.status===304?null:await response.json(),serverTime=Math.floor(new Date(response.headers.get('Date')??Date.now()).getTime()/1000)
      if(!Number.isSafeInteger(serverTime))throw new Error('响应时间无效')
      return {status:response.status,data,etag:response.headers.get('ETag')??'',serverTime}
    }catch{
      throw Object.assign(new Error('交易所 Mock 响应格式无效，请检查 STOCK_EXCHANGE_URL 是否指向交易所 API'),{code:'STOCK_INVALID_RESPONSE'})
    }
  }
  const monthOf=time=>new Date(time+8*3600000).toISOString().slice(0,7)
  function signedHistory(i,month,points,count=0,digest=''){
    const result={instanceId:i.id,publicKey:i.pub,month,issuedAt:Math.floor(Date.now()/1000),points,count,digest}
    const text=`mmex-history-v1\n${i.id}\n${i.pub}\n${month}\n${result.issuedAt}\n${count}\n${digest}\n`+points.map(p=>`${p.time}:${p.actionPoints}\n`).join('')
    result.signature=sign(null,Buffer.from(text),i.privateKey).toString('base64');return result
  }
  async function synchronize(name){
    const i=identity(name);if(!i.upload||i.busy||Date.now()<i.next)return
    i.busy=true
    try{
      const row=snapshot(name)
      if(row){const time=row.observedAtMillis??row.observedAt*1000,point={time,actionPoints:row.actionPoints}
        if(i.history.get(time)?.actionPoints!==point.actionPoints){i.history.set(time,point);i.pending.add(time);i.checked=0;mkdirSync(i.directory,{recursive:true});writeFileSync(i.path+'.tmp',JSON.stringify([...i.history.values()]),{mode:0o600});renameSync(i.path+'.tmp',i.path)}
      }
      const pending=[...i.pending].filter(t=>t<=Date.now()+60000).sort((a,b)=>b-a),month=pending.length?monthOf(pending[0]):monthOf(Date.now())
      if(pending.length){const batch=pending.filter(t=>monthOf(t)===month).sort((a,b)=>a-b),reply=await remote('/quote-history','POST',{report:signedHistory(i,month,batch.map(t=>i.history.get(t)))},i.upload,i.key)
        if(reply.status>=400)throw new Error(reply.data.error?.message??'历史补传失败');batch.forEach(t=>i.pending.delete(t));i.checked=0
      }else if(Date.now()>=i.checked){
        const points=[...i.history.values()].filter(p=>monthOf(p.time)===month).sort((a,b)=>a.time-b.time),digest=createHash('sha256').update(points.map(p=>`${p.time}:${p.actionPoints}\n`).join('')).digest('hex')
        const manifest=await remote('/quote-history/manifest?month='+month,'GET',null,i.upload,i.key)
        if(manifest.status>=400)throw new Error('历史校对失败')
        if(manifest.data.count!==points.length||manifest.data.digest!==digest){points.forEach(p=>i.pending.add(p.time))}else{
          const reply=await remote('/quote-history','POST',{report:signedHistory(i,month,[],points.length,digest)},i.upload,i.key)
          if(reply.status>=400)throw new Error('历史摘要确认失败');i.checked=Date.now()+300000
        }
      }
      i.next=0
    }catch{i.next=Date.now()+1000}finally{i.busy=false;if(i.pending.size&&i.next===0)void synchronize(name)}
  }
  const timer=setInterval(()=>{for(const name of instances.keys())void synchronize(name)},250);timer.unref()
  function stockPath(path){
    const parsed=new URL(path,'http://mock.local'),patterns={period:/^(time|day|m5|m10|m20|m30|m60)$/,month:/^\d{4}-\d{2}$/,day:/^\d{4}-\d{2}-\d{2}$/}
    return parsed.origin==='http://mock.local'&&!parsed.hash&&/^\/stocks\/[1-9]\d*$/.test(parsed.pathname)&&[...parsed.searchParams.keys()].every(k=>patterns[k]?.test(parsed.searchParams.get(k))&&parsed.searchParams.getAll(k).length===1)
  }
  return {
    subscribe(listener){listeners.add(listener);void listen();return ()=>{listeners.delete(listener);if(!listeners.size)streamController?.abort()}},
    close(){clearInterval(timer);listeners.clear();streamController?.abort()},
    status(name){const i=identity(name),row=snapshot(name);return {url,instance:name,instanceId:i.id,bindingKey:i.key,bound:!!i.player,boundUsername:i.player?.username??'',authenticated:!!i.token,message:i.player?'Mock 实例账户已永久绑定':'Mock：直接使用当前实例行动力',lastObservedAt:row?.observedAt??0,snapshot:row}},
    rebuild(name,{confirm=false,scope='instance'}={}){
      const plan={instance:name,scope:'instance',affectedInstances:[name],rebuilt:false}
      if(!confirm)return plan
      if(scope!=='instance')throw Object.assign(new Error('重建范围已变化，请重新确认'),{code:'STOCK_REBUILD_SCOPE_CHANGED',details:plan})
      const previous=instances.get(name);if(previous){previous.upload='';previous.token='';previous.pending.clear()}
      instances.delete(name);generations.set(name,(generations.get(name)??0)+1)
      return {...plan,rebuilt:true}
    },
    async request(name,{path,method='GET',body=null,etag=''}){
      const i=identity(name)
      const publicRequest=method==='GET'&&( ['/meta','/market','/seasons'].includes(path)||/^\/history\/[1-9]\d*$/.test(path)||stockPath(path))
      const auth=method==='POST'&&['/register','/login'].includes(path)
      const privateRequest=method==='GET'&&['/account','/orders'].includes(path)||method==='POST'&&['/orders','/watchlist','/logout','/sync'].includes(path)||method==='DELETE'&&/^\/orders\/[1-9]\d*$/.test(path)
      if(!(publicRequest||auth||privateRequest))throw Object.assign(new Error('接口不在实例代理白名单中'),{code:'INVALID_PARAMS'})
      if(body&&Object.keys(body).some(k=>['report','evidence','instanceId','actionPoints','observedAt','token','uploadToken','publicKey','points','digest','signature'].includes(k)))throw Object.assign(new Error('浏览器不能提供实例身份或报价'),{code:'INVALID_PARAMS'})
      if(path==='/logout'){i.token='';return {status:200,data:{ok:true},etag:'',serverTime:Math.floor(Date.now()/1000)}}
      if(publicRequest)return remote(path,method,null,'','',etag)
      if(auth){
        if(path==='/register'&&i.player)throw Object.assign(new Error('当前实例已永久绑定账户'),{code:'INSTANCE_TAKEN'})
        const meta=await remote('/meta');if(!meta.data.mock)throw new Error('交易所不是 Mock 服务')
        const reply=await remote(path,method,{...body,report:report(name)})
        if(reply.status<400){
          const result=reply.data
          if(result.player.binding.key!==i.key||i.player&&i.player.id!==result.player.id)throw new Error('实例绑定不匹配')
          i.token=result.token;i.player=result.player;i.upload=result.uploadToken??i.upload
          if(!i.upload)i.upload=(await remote('/upload-token','POST',{},i.token,i.key)).data.uploadToken
          reply.data={token:'instance-session',player:result.player}
        }
        return reply
      }
      if(!i.token)return {status:401,data:{error:{code:'UNAUTHORIZED',message:'请登录当前实例绑定的账户'}},etag:'',serverTime:Math.floor(Date.now()/1000)}
      if(path==='/sync')return remote('/quotes','POST',{report:report(name)},i.upload,i.key)
      const reply=await remote(path,method,body,i.token,i.key)
      if(path==='/account'&&reply.status===200&&reply.data?.player?.id===i.player?.id)i.player=reply.data.player
      if(reply.status===401)i.token=''
      return reply
    }
  }
}
