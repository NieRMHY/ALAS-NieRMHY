/** 原生交易终端，玩家数据错误和重建入口只在本页展示。 */
import {useEffect,useState,useRef,useCallback} from 'react'
import {useParams} from 'react-router-dom'
import {api} from '../api/client'
import type {StockExchangeRebuild,StockExchangeStatus} from '../api/types'
import {useConnection} from '../app/context'
import {ErrorBox,Loading} from '../components/ui'
import {ExchangeProvider,isPlayerDataError} from '../stock/api'
import {App as TradingTerminal} from '../stock/App'
import {OverviewLink} from '../stock/OverviewLink'
import {StockThemeProvider,useStockTheme} from '../stock/theme'
import '../stock/styles.css'
import './stock-exchange.css'
import '../stock/theme.css'

export function StockExchange(){
  return <StockThemeProvider><StockExchangeContent/></StockThemeProvider>
}

function StockExchangeContent(){
  const {theme}=useStockTheme()
  const {instance=''}=useParams(),connection=useConnection()
  const [status,setStatus]=useState<StockExchangeStatus>(),[error,setError]=useState<Error>()
  const [plan,setPlan]=useState<StockExchangeRebuild>(),[accepted,setAccepted]=useState(false),[busy,setBusy]=useState(false),[recoveryError,setRecoveryError]=useState('')
  const [generation,setGeneration]=useState(0)
  const current=useRef(instance);current.current=instance
  const failed=useCallback((error:Error)=>{if(current.current===instance)setError(error)},[instance])
  const sessionChanged=useCallback(()=>{void api.request('stock.status',{instance}).then(next=>{if(current.current===next.instance){setStatus(next);setError(undefined)}}).catch(failed)},[instance,failed])
  useEffect(()=>{setStatus(undefined);setError(undefined);setPlan(undefined);setAccepted(false);setRecoveryError('');let active=true
    const load=async()=>{if(connection!=='ready')return;try{const next=await api.request('stock.status',{instance});if(active){setStatus(next);setError(undefined)}}catch(e){if(active)setError(e as Error)}}
    let busy=false,queued=false
    const refresh=async()=>{queued=true;if(busy)return;busy=true;try{do{queued=false;await load()}while(queued&&active)}finally{busy=false}}
    void refresh()
    const unsubscribe=api.onEvent(event=>{if(event.topic==='stock'&&(event.data as {instance?:string}).instance===instance)void refresh()})
    return ()=>{active=false;unsubscribe()}
  },[instance,connection,generation])
  async function rebuild(confirm=false){
    setBusy(true);setRecoveryError('')
    try{
      const result=await api.request('stock.rebuild',{instance,confirm,scope:plan?.scope??'instance'})
      if(current.current!==instance)return
      if(result.rebuilt){setGeneration(value=>value+1)}else{setPlan(result);setAccepted(false)}
    }catch(error){if(current.current===instance){setRecoveryError((error as Error).message);if(confirm){setPlan(undefined);setAccepted(false)}}}
    finally{if(current.current===instance)setBusy(false)}
  }
  const unavailable=!status||!!error
  return <section className="stock-exchange-page" data-stock-theme={theme}>
    {unavailable?<div className="stock-terminal stock-exchange-loading">
      {error?<>
        <h2>{isPlayerDataError(error)?'玩家数据需要处理':'交易所暂时无法连接'}</h2>
        <ErrorBox message={error.message}/>
        {isPlayerDataError(error)&&<p className="muted">此问题仅影响茗交所。你可以恢复完整备份，或完全重建本地账户后重新开户。</p>}
        {plan?<section className="stock-rebuild-confirm" aria-label="确认账户重建">
          <p>{plan.scope==='all'?'共享玩家数据损坏，需要重建所有本地交易账户。':'将重建当前实例的本地交易账户。'}</p>
          <p>涉及实例：{plan.affectedInstances.join('、')}</p>
          <p>重建会清除本地交易身份、绑定、会话与补传历史，并保留一份原数据备份。原远端账户仍然存在，新账户需使用新用户名。实例配置、调度方案和资源统计会保留。</p>
          <label className="check"><input type="checkbox" checked={accepted} disabled={busy} onChange={event=>setAccepted(event.target.checked)}/>我了解重建范围及后果</label>
          <div className="stock-state-actions"><button onClick={()=>setPlan(undefined)} disabled={busy}>取消</button><button className="primary" onClick={()=>void rebuild(true)} disabled={busy||!accepted}>{busy?'正在重建…':'确认完全重建'}</button></div>
        </section>:<div className="stock-state-actions"><button onClick={()=>setGeneration(value=>value+1)} disabled={busy}>重试连接</button>{isPlayerDataError(error)&&<button className="primary" onClick={()=>void rebuild()} disabled={busy}>{busy?'正在检查…':'完全重建账户'}</button>}</div>}
        {recoveryError&&<p role="alert">{recoveryError}</p>}
      </>:<Loading/>}
      <OverviewLink instance={instance}/>
    </div>:<div className="stock-terminal" data-stock-theme={theme}><ExchangeProvider key={`${instance}:${generation}`} instance={instance} status={status!} onSessionChanged={sessionChanged} onPlayerDataError={failed}><TradingTerminal/></ExchangeProvider></div>}
  </section>
}
