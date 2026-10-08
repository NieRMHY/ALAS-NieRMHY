// 公开站点标识固定在前端；私密密钥仅由 Go 后端环境变量读取。
export const RECAPTCHA_SITE_KEY='6Ldu7N4tAAAAABEvkf8KUza3x6rxHGLm1dP5gpMq'
export const RECAPTCHA_TEST_SITE_KEY='6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI'
export interface Recaptcha {
  render:(element:HTMLElement,options:Record<string,unknown>)=>number
  reset:(id:number)=>void
}
declare global {interface Window {grecaptcha?:Recaptcha;mmexRecaptchaReady?:()=>void}}
let scriptPromise:Promise<Recaptcha>|undefined

export function loadRecaptcha():Promise<Recaptcha>{
  if(typeof window.grecaptcha?.render==='function')return Promise.resolve(window.grecaptcha)
  if(!scriptPromise)scriptPromise=new Promise((resolve,reject)=>{
    const script=document.createElement('script')
    let settled=false
    const finish=(error?:Error)=>{
      if(settled)return
      settled=true
      window.clearTimeout(timeout)
      if(window.mmexRecaptchaReady===ready)delete window.mmexRecaptchaReady
      if(error){script.remove();scriptPromise=undefined;reject(error)}
      else resolve(window.grecaptcha!)
    }
    // api.js 的 load 事件早于依赖就绪，必须等待 Google 的 onload 回调。
    const ready=()=>finish(typeof window.grecaptcha?.render==='function'?undefined:new Error('验证码初始化失败，请重试'))
    const timeout=window.setTimeout(()=>finish(new Error('验证码加载超时，请检查网络后重试')),20000)
    window.mmexRecaptchaReady=ready
    script.src='https://www.recaptcha.net/recaptcha/api.js?onload=mmexRecaptchaReady&render=explicit&hl=zh-CN'
    script.async=true
    script.defer=true
    script.onerror=()=>finish(new Error('验证码加载失败，请检查网络后重试'))
    document.head.append(script)
  })
  return scriptPromise
}
