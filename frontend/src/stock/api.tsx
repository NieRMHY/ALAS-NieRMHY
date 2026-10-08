import {createContext,useContext,useMemo,type ReactNode} from 'react'
import {api as pilotAPI} from '../api/client'
import type {StockExchangeStatus} from '../api/types'
import type {Parameters as RequestParameters} from '../api/generated'

export class ApiError extends Error {constructor(message:string,public code:string,public status:number){super(message)}}
export interface Reply<T=unknown>{status:number;data:T|null;etag:string;serverTime:number}
export interface ExchangeUpdate {revision?:number;serverTime?:number;online?:boolean;instance?:string}
interface Transport {
  <T>(path:string,body?:unknown,token?:string,method?:string):Promise<T>
  response:<T>(path:string,etag?:string)=>Promise<Reply<T>>
  subscribe:(listener:(update:ExchangeUpdate)=>void)=>()=>void
}
const Context=createContext<{api:Transport;status:StockExchangeStatus}|null>(null)
export const isPlayerDataError=(error:Error)=>['STOCK_STORAGE_DAMAGED','STOCK_IDENTITY_DAMAGED','STOCK_HISTORY_UNAVAILABLE','STOCK_ORIGIN_CHANGED','INSTANCE_MISMATCH'].includes((error as Error&{code?:string}).code??'')
export function ExchangeProvider({instance,status,children,onSessionChanged,onPlayerDataError}:{instance:string;status:StockExchangeStatus;children:ReactNode;onSessionChanged:()=>void;onPlayerDataError:(error:Error)=>void}){
  const transport=useMemo(()=>{
    function accepted<T>(response:Reply<T&{error?:{message:string;code:string}}>){
      if(response.status>=400){
        const error=new ApiError(response.data?.error?.message??'交易所暂不可用',response.data?.error?.code??'HTTP_ERROR',response.status)
        if(isPlayerDataError(error))onPlayerDataError(error)
        throw error
      }
      return response
    }
    async function send<T>(params:RequestParameters['stock.request']){
      try{return await pilotAPI.request('stock.request',params) as Reply<T&{error?:{message:string;code:string}}>}
      catch(error){if(isPlayerDataError(error as Error))onPlayerDataError(error as Error);throw error}
    }
    async function request<T>(path:string,body?:unknown,_token?:string,method?:string):Promise<T>{
      const response=await send<T>({instance,path,method:(method??(body===undefined?'GET':'POST')) as 'GET'|'POST'|'DELETE',body:(body??null) as Record<string,unknown>|null,etag:''})
      accepted(response)
      if(['/register','/login','/logout'].includes(path))onSessionChanged()
      return response.data as T
    }
    const api=request as Transport
    api.response=async <T,>(path:string,etag='')=>{
      const response=await send<T>({instance,path,method:'GET',body:null,etag})
      accepted(response)
      return response as Reply<T>
    }
    api.subscribe=listener=>pilotAPI.onEvent(event=>{
      if(event.topic==='stock'){
        const update=event.data as ExchangeUpdate
        if(update.instance===instance)listener(update)
      }
    })
    return api
  },[instance,onSessionChanged,onPlayerDataError])
  return <Context.Provider value={{api:transport,status}}>{children}</Context.Provider>
}
export const useExchange=()=>useContext(Context)!
export const useAPI=()=>useExchange().api
export const money=(n:number,digits=2)=>new Intl.NumberFormat('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(n/100)
export const compact=(n:number)=>Math.abs(n)>=10000000000?`${(n/10000000000).toFixed(2)} 亿`:Math.abs(n)>=1000000?`${(n/1000000).toFixed(2)} 万`:money(n)
export const percent=(ppm:number)=>`${ppm>=0?'+':''}${(ppm/10000).toFixed(2)}%`
export const quoteChange=(price:number,open:number)=>open>0?Math.round((price-open)/open*1000000):0
export const datetime=(t:number)=>new Date(t*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})
export const feesTotal=(f:{commission:number;stamp:number;levy:number;borrow:number;financing?:number})=>f.commission+f.stamp+f.levy+f.borrow+(f.financing??0)
export const sideName:Record<string,string>={buy:'买入',sell:'卖出',short:'卖空',cover:'回补'}
export const statusName:Record<string,string>={pending:'待触发',filled:'已成交',cancelled:'已撤销',expired:'已过期',rejected:'已拒绝'}
