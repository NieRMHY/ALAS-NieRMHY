import {useEffect,useRef,useState} from 'react'
import type {Meta} from './types'
import {useStockTheme} from './theme'
import {loadRecaptcha,RECAPTCHA_SITE_KEY,RECAPTCHA_TEST_SITE_KEY,type Recaptcha} from './recaptcha'

export function Captcha({meta,purpose,onToken,reset}:{meta:Meta;purpose:string;onToken:(token:string)=>void;reset:number}){
  const {theme}=useStockTheme()
  const ref=useRef<HTMLDivElement>(null),callback=useRef(onToken)
  callback.current=onToken
  const [error,setError]=useState(''),[retry,setRetry]=useState(0)
  useEffect(()=>{
    callback.current('');setError('')
    const container=ref.current!
    const host=document.createElement('div')
    container.append(host)
    const fit=()=>{const scale=Math.min(1,container.clientWidth/302);host.style.transform=scale<1?`scale(${scale})`:'';host.style.transformOrigin='center top'}
    const observer=new ResizeObserver(fit);observer.observe(container);fit()
    let stopped=false,id:number|undefined,api:Recaptcha|undefined
    void loadRecaptcha().then(loaded=>{
      if(stopped)return
      api=loaded
      // purpose 仅用于切换表单时重建组件；当前 v2 复选框不发送 action。
      id=api.render(host,{sitekey:meta.mock?RECAPTCHA_TEST_SITE_KEY:RECAPTCHA_SITE_KEY,theme,
        callback:(token:string)=>{if(!stopped){callback.current(token);setError('')}},
        'expired-callback':()=>{if(!stopped){callback.current('');setError('验证码已过期，请重新验证')}},
        'error-callback':()=>{if(!stopped){callback.current('');setError('验证码失败，请重试')}}})
    }).catch((error:Error)=>{if(!stopped){callback.current('');setError(error.message)}})
    return ()=>{
      stopped=true
      observer.disconnect()
      // 先 reset 再移除 DOM，且 0 也是有效组件 ID；旧回调不能恢复已清空的 token。
      if(id!==undefined)api?.reset(id)
      host.remove()
    }
  },[meta.mock,purpose,reset,retry,theme])
  return <div className="captcha"><div className="captcha-widget" ref={ref}/>{meta.mock&&<small className="muted">Google reCAPTCHA 官方测试验证码</small>}{error&&<div className="inline-error">{error} <button type="button" onClick={()=>setRetry(value=>value+1)}>重试</button></div>}</div>
}
