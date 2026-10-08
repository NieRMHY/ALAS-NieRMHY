import {useEffect,useRef,useState} from 'react'
import {useAPI} from './api'
import type {ChartPeriod,StockDetail} from './types'

export function shanghaiMonth(){return new Date(Date.now()+8*3600000).toISOString().slice(0,7)}
export function useStockDetail(id:number|undefined,period:ChartPeriod,month:string,day:string,refresh:number,enabled:boolean){
  const api=useAPI(),[detail,setDetail]=useState<StockDetail>(),[error,setError]=useState(''),[loading,setLoading]=useState(false),[updated,setUpdated]=useState(0)
  const sequence=useRef(0)
  const request=useRef<()=>void>(()=>{})
  useEffect(()=>{
    if(!id||!enabled)return
    const generation=++sequence.current;let stopped=false,busy=false,queued=false,etag='',revision:number|undefined
    setDetail(undefined);setError('');setLoading(true)
    const query=new URLSearchParams({period,month});if(day)query.set('day',day)
    const run=async()=>{
      if(stopped)return;queued=true;if(busy)return;busy=true;queued=false
      try{const reply=await api.response<StockDetail>(`/stocks/${id}?${query}`,etag)
        if(stopped||generation!==sequence.current)return
        if(reply.status!==304){etag=reply.etag;setDetail(reply.data!)}
        setUpdated(reply.serverTime);setError('')
      }catch(e){if(!stopped&&generation===sequence.current)setError((e as Error).message)}finally{busy=false;if(!stopped&&generation===sequence.current){setLoading(false);if(queued)void run()}}
    }
    request.current=()=>void run()
    void run()
    const unsubscribe=api.subscribe(update=>{if(update.online===false)return;if(update.revision===undefined||update.revision!==revision){revision=update.revision;void run()}})
    const visible=()=>{if(document.visibilityState==='visible')void run()};document.addEventListener('visibilitychange',visible)
    return ()=>{stopped=true;request.current=()=>{};unsubscribe();document.removeEventListener('visibilitychange',visible)}
  },[api,id,period,month,day,enabled])
  useEffect(()=>{request.current()},[refresh])
  return {detail,error,loading,updated}
}
