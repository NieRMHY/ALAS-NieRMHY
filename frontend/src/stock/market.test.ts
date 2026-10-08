import {describe,expect,it} from 'vitest'
import {defaultFilters,filterStocks,positionPnl,sortStocks} from './market'
import type {Position,Stock} from './types'

const stock=(id:number,price:number,open=10000,overrides:Partial<Stock>={}):Stock=>({id,username:`玩家${id}`,symbol:`MM${id}`,quote:{price,previous:price,observedAt:1000,uploadedAt:1000},open,stale:false,disabled:false,delisted:false,...overrides})
const stocks=[stock(1,12000),stock(2,8000),stock(3,10000),stock(4,10000,0),stock(5,10000,10000,{delisted:true})]
const apply=(filters={},scope='all',watchlist:number[]=[])=>filterStocks(stocks,{...defaultFilters,...filters},'',scope,watchlist,{},1,1060)

describe('证券过滤与排序',()=>{
  it('默认排除退市，显式切换可找回退市证券',()=>{expect(apply().map(s=>s.id)).toEqual([1,2,3,4]);expect(apply({listing:'delisted'}).map(s=>s.id)).toEqual([5])})
  it('自选与上市状态组合使用，保留已退市自选供查询',()=>{expect(apply({},'watchlist',[1,5]).map(s=>s.id)).toEqual([1]);expect(apply({listing:'all'},'watchlist',[1,5]).map(s=>s.id)).toEqual([1,5])})
  it('价格以模拟币、涨跌幅以百分比筛选；缺开盘价不冒充平盘',()=>{expect(apply({minPrice:'100',maxPrice:'120',minChange:'0',maxChange:'20'}).map(s=>s.id)).toEqual([1,3]);expect(apply({direction:'flat'}).map(s=>s.id)).toEqual([3]);expect(apply({direction:'unknown'}).map(s=>s.id)).toEqual([4])})
  it('可交易报价排除自己的股票，过期时间边界包含最新一分钟',()=>{expect(apply({quote:'valid'}).map(s=>s.id)).toEqual([2,3,4]);expect(apply({recent:'1'})).toHaveLength(4)})
  it('排序有两个方向，缺开盘价始终排在涨跌排序末尾',()=>{expect(sortStocks(stocks.slice(0,4),'change-desc').map(s=>s.id)).toEqual([1,3,2,4]);expect(sortStocks(stocks.slice(0,4),'change-asc').map(s=>s.id)).toEqual([2,3,1,4])})
})

describe('总浮动盈亏',()=>{
  it('汇总多头与空头账面盈亏，融资借款不重复扣减持仓成本',()=>{
    const long={quantity:2,cost:200500,loan:100000} as Position,short={quantity:-3,cost:449500} as Position
    expect(positionPnl(long,110000)+positionPnl(short,140000)).toBe(49000)
    expect(positionPnl(long,90000)+positionPnl(short,160000)).toBe(-51000)
  })
})
