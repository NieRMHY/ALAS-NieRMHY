import type {Candle} from './types'

export type Indicator='MA'|'EXPMA'|'BOLL'|'ENE'|'BBI'
export type Values=(number|null)[]
export interface IndicatorLine {name:string;color:string;values:Values;dash?:boolean}
export const indicatorNotes:Record<Indicator,string>={
  MA:'MA5 / 10 / 20：最近 5、10、20 根 K 线收盘价的算术平均，观察短中期方向。',
  EXPMA:'EXPMA12 / 50：指数平均，权重 α = 2 / (N + 1)，以第一根收盘价初始化；近期价格权重更大。',
  BOLL:'BOLL(20,2)：中轨 MA20，上下轨为中轨 ± 2 倍总体标准差，观察价格波动范围。',
  ENE:'ENE(10,11,9)：MA10 上浮 11% 为上轨、下浮 9% 为下轨，中轨为两轨平均。',
  BBI:'BBI：(MA3 + MA6 + MA12 + MA24) / 4，价格高于 BBI 且均线向上时为多头参考。',
}
export function sma(values:number[],period:number):Values {
  let sum=0
  return values.map((value,i)=>{sum+=value;if(i>=period)sum-=values[i-period];return i+1<period?null:sum/period})
}
export function ema(values:number[],period:number):number[] {
  let previous=values[0]??0;const weight=2/(period+1)
  return values.map((value,i)=>{previous=i?value*weight+previous*(1-weight):value;return previous})
}
export function indicatorLines(bars:Candle[],selected:Indicator[]):IndicatorLine[] {
  const close=bars.map(b=>b.close/100),lines:IndicatorLine[]=[]
  const line=(name:string,color:string,values:Values,dash=false)=>lines.push({name,color,values,dash})
  if(selected.includes('MA')){line('MA5','#e7c482',sma(close,5));line('MA10','#baa0dc',sma(close,10));line('MA20','#82b9d5',sma(close,20))}
  if(selected.includes('EXPMA')){line('EXPMA12','#dfb176',ema(close,12));line('EXPMA50','#aa98d9',ema(close,50))}
  if(selected.includes('BOLL')){
    const mean=sma(close,20),deviation=mean.map((m,i)=>m===null?null:Math.sqrt(close.slice(i-19,i+1).reduce((sum,c)=>sum+(c-m)**2,0)/20))
    line('BOLL MID','#86b9d1',mean);line('BOLL UP','#b49cce',mean.map((m,i)=>m===null?null:m+2*deviation[i]!));line('BOLL LOW','#b49cce',mean.map((m,i)=>m===null?null:m-2*deviation[i]!))
  }
  if(selected.includes('ENE')){
    const mean=sma(close,10),upper=mean.map(m=>m===null?null:m*1.11),lower=mean.map(m=>m===null?null:m*.91)
    line('ENE UP','#d29ca3',upper,true);line('ENE LOW','#8fbea9',lower,true);line('ENE MID','#c8b477',mean.map(m=>m===null?null:m*1.01))
  }
  if(selected.includes('BBI')){const averages=[3,6,12,24].map(n=>sma(close,n));line('BBI','#d5c6a0',close.map((_,i)=>averages.some(a=>a[i]===null)?null:averages.reduce((sum,a)=>sum+a[i]!,0)/4))}
  return lines
}
export function macd(bars:Candle[]) {
  const close=bars.map(b=>b.close/100),fast=ema(close,12),slow=ema(close,26),dif=fast.map((v,i)=>v-slow[i]),dea=ema(dif,9)
  return {dif,dea,histogram:dif.map((v,i)=>(v-dea[i])*2)}
}
export function trend(bars:Candle[]):{label:string;direction:'rise'|'fall'|'muted';explanation:string} {
  if(bars.length<25)return {label:'样本不足',direction:'muted',explanation:'需要至少 25 根 K 线才能比较相邻两根 BBI 的方向。'}
  const bbi=indicatorLines(bars,['BBI'])[0].values,last=bars.length-1,close=bars[last].close/100
  if(close>bbi[last]! && bbi[last]!>bbi[last-1]!)return {label:'多头趋势',direction:'rise',explanation:'收盘价高于 BBI，且 BBI 向上。'}
  if(close<bbi[last]! && bbi[last]!<bbi[last-1]!)return {label:'空头趋势',direction:'fall',explanation:'收盘价低于 BBI，且 BBI 向下。'}
  return {label:'震荡整理',direction:'muted',explanation:'价格与 BBI 方向未形成一致的多空信号。'}
}
