import {describe,expect,it} from 'vitest'
import {ema,indicatorLines,macd,sma,trend} from './indicators'
import type {Candle} from './types'

const candles=(prices:number[]):Candle[]=>prices.map((price,i)=>({time:1700000000000+i*60000,open:price*100,high:price*100,low:price*100,close:price*100,samples:1,volume:0,turnover:0,buyVolume:0,sellVolume:0}))
describe('金融指标使用相应周期的收盘价，不填造不足样本',()=>{
  it('MA 与指数均线具有正确窗口、权重和初始化',()=>{
    expect(sma([1,2,3,4,5],3)).toEqual([null,null,2,3,4])
    const values=ema([1,2,3],2);expect(values[0]).toBe(1);expect(values[1]).toBeCloseTo(5/3);expect(values[2]).toBeCloseTo(23/9)
    const short=indicatorLines(candles([100,101,102]),['MA','BOLL','ENE','BBI']);expect(short.every(l=>l.values.every(v=>v===null))).toBe(true)
  })
  it('BOLL 总体标准差与 ENE 上下轨准确',()=>{
    const bars=candles(Array(25).fill(100)),boll=indicatorLines(bars,['BOLL']),ene=indicatorLines(bars,['ENE'])
    expect(boll.map(l=>l.values.at(-1))).toEqual([100,100,100]);expect(ene[0].values.at(-1)).toBeCloseTo(111);expect(ene[1].values.at(-1)).toBeCloseTo(91);expect(ene[2].values.at(-1)).toBeCloseTo(101)
    const varying=indicatorLines(candles(Array.from({length:20},(_,i)=>i+1)),['BOLL']);expect(varying[1].values.at(-1)).toBeCloseTo(10.5+2*Math.sqrt(33.25));expect(varying[2].values.at(-1)).toBeCloseTo(10.5-2*Math.sqrt(33.25))
  })
  it('BBI、多空方向和 MACD 计算一致',()=>{
    const up=candles(Array.from({length:30},(_,i)=>i+1)),down=candles(Array.from({length:30},(_,i)=>30-i))
    expect(indicatorLines(up.slice(0,24),['BBI'])[0].values.at(-1)).toBeCloseTo(18.875)
    expect(trend(up).direction).toBe('rise');expect(trend(down).direction).toBe('fall');expect(trend(up.slice(0,24)).label).toBe('样本不足');expect(trend(candles(Array(30).fill(100))).label).toBe('震荡整理')
    const constant=macd(candles(Array(50).fill(100)));expect(constant.histogram.every(v=>v===0)).toBe(true)
    const changing=macd(up);expect(changing.histogram.at(-1)).toBeCloseTo(2*(changing.dif.at(-1)!-changing.dea.at(-1)!))
  })
})
