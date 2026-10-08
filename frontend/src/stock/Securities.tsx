import {useState} from 'react'
import {Globe2,Search,SlidersHorizontal,Star} from 'lucide-react'
import {money,percent,quoteChange} from './api'
import {Sparkline} from './Charts'
import {defaultFilters,filterStocks,sortStocks,type MarketFilters} from './market'
import type {Account,Market,Stock} from './types'
import './securities.css'

export function Securities({market,account,selected,onSelect,onWatch,busy}:{market:Market;account?:Account;selected?:number;onSelect:(id:number)=>void;onWatch:(stock:Stock)=>void;busy?:number}){
  const [scope,setScope]=useState('all'),[query,setQuery]=useState(''),[filters,setFilters]=useState<MarketFilters>(defaultFilters),[sort,setSort]=useState('id-asc')
  const watchlist=account?.player.watchlist??[],positions=account?.player.positions??{}
  const filtered=sortStocks(filterStocks(market.stocks,filters,query,scope,watchlist,positions,account?.player.id,market.serverTime),sort)
  const active=Object.keys(defaultFilters).filter(key=>filters[key as keyof MarketFilters]!==defaultFilters[key as keyof MarketFilters]).length
  const field=(key:keyof MarketFilters,value:string)=>setFilters(current=>({...current,[key]:value}))
  return <section className="panel watchlist"><div className="panel-title"><h3>{scope==='watchlist'?'自选股':scope==='positions'?'持仓证券':'全部证券'} <small>{filtered.length} / {market.stocks.length}</small></h3><Globe2 size={15}/></div>
    <div className="security-scopes" aria-label="证券范围">{[['all','全部证券'],['watchlist',`自选股 (${watchlist.length})`],['positions','持仓证券']].map(([id,label])=><button key={id} aria-pressed={scope===id} className={scope===id?'active':''} onClick={()=>setScope(id)}>{label}</button>)}</div>
    <label className="search"><Search size={15}/><input aria-label="搜索证券" placeholder="名称 / 证券代码" value={query} onChange={event=>setQuery(event.target.value)}/></label>
    <details className="security-filters"><summary><SlidersHorizontal size={14}/>证券过滤器 <small>{active?`${active} 项已调整`:'默认隐藏退市股票'}</small></summary><div className="security-filter-fields">
      <label>上市状态<select value={filters.listing} onChange={e=>field('listing',e.target.value)}><option value="listed">未退市</option><option value="all">全部（含退市）</option><option value="delisted">已退市</option></select></label>
      <label>报价状态<select value={filters.quote} onChange={e=>field('quote',e.target.value)}><option value="all">全部状态</option><option value="valid">可交易报价</option><option value="stale">报价过期</option><option value="zero">零报价</option><option value="disabled">停牌</option></select></label>
      <label>涨跌方向<select value={filters.direction} onChange={e=>field('direction',e.target.value)}><option value="all">全部涨跌</option><option value="rise">上涨</option><option value="fall">下跌</option><option value="flat">平盘</option><option value="unknown">暂无开盘价</option></select></label>
      <label>证券归属<select value={filters.ownership} onChange={e=>field('ownership',e.target.value)}><option value="all">全部玩家</option><option value="others">其他玩家</option><option value="self">我的股票</option></select></label>
      <label>最低价格<input aria-label="最低价格" type="number" min="0" step="0.01" placeholder="不限" value={filters.minPrice} onChange={e=>field('minPrice',e.target.value)}/></label><label>最高价格<input aria-label="最高价格" type="number" min="0" step="0.01" placeholder="不限" value={filters.maxPrice} onChange={e=>field('maxPrice',e.target.value)}/></label>
      <label>最低涨跌幅 (%)<input type="number" step="0.01" placeholder="不限" value={filters.minChange} onChange={e=>field('minChange',e.target.value)}/></label><label>最高涨跌幅 (%)<input type="number" step="0.01" placeholder="不限" value={filters.maxChange} onChange={e=>field('maxChange',e.target.value)}/></label>
      <label>报价更新时间<select value={filters.recent} onChange={e=>field('recent',e.target.value)}><option value="all">不限时间</option><option value="1">最近 1 分钟</option><option value="5">最近 5 分钟</option><option value="30">最近 30 分钟</option><option value="1440">最近 24 小时</option></select></label>
      <button className="small-button" onClick={()=>{setFilters(defaultFilters);setQuery('');setSort('id-asc')}}>重置过滤器</button>
    </div></details>
    <label className="security-sort">排序<select aria-label="证券排序" value={sort} onChange={e=>setSort(e.target.value)}>{[['id-asc','证券代码 ↑'],['id-desc','证券代码 ↓'],['name-asc','名称 ↑'],['name-desc','名称 ↓'],['price-desc','价格高到低'],['price-asc','价格低到高'],['change-desc','涨幅高到低'],['change-asc','涨幅低到高'],['updated-desc','报价最新优先'],['updated-asc','报价最早优先']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
    <div className="watchlist-head"><span>证券 / 代码</span><button onClick={()=>setSort(sort==='price-desc'?'price-asc':'price-desc')}>最新价 ↕</button><button onClick={()=>setSort(sort==='change-desc'?'change-asc':'change-desc')}>涨跌 ↕</button></div>
    <div className="stock-list">{filtered.map(stock=>{const change=quoteChange(stock.quote.price,stock.open),watched=watchlist.includes(stock.id);return <div className="stock-list-row" key={stock.id}><button className={`watch-button ${watched?'active':''}`} aria-label={`${watched?'移除自选股':'添加自选股'} ${stock.username}`} aria-pressed={watched} title={watched?'移除自选股':'添加自选股'} disabled={!account||busy!==undefined} onClick={()=>onWatch(stock)}><Star size={16} fill={watched?'currentColor':'none'}/></button><button className={`stock-row ${selected===stock.id?'selected':''}`} onClick={()=>onSelect(stock.id)}><span><strong>{stock.username}{stock.id===account?.player.id&&<small>我</small>}</strong><small>{stock.symbol}{stock.delisted?' · 退市':stock.disabled?' · 停牌':stock.stale?' · 过期':''}</small></span><span><b>{money(stock.quote.price)}</b><Sparkline value={stock.quote.price} open={stock.open}/></span><span className={change>=0?'rise':'fall'}>{stock.open>0?percent(change):'—'}</span></button></div>})}{filtered.length===0&&<div className="empty-state">{scope==='watchlist'&&!watchlist.length?'点击证券旁的星标添加自选股':'没有符合当前过滤条件的证券'}</div>}</div>
    <div className="watchlist-foot"><i/>1 行动力 = 1 模拟币 · 实时更新</div></section>
}
