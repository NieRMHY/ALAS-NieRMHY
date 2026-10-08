import {quoteChange} from './api'
import type {Position,Stock} from './types'

export const defaultFilters={listing:'listed',quote:'all',direction:'all',ownership:'all',minPrice:'',maxPrice:'',minChange:'',maxChange:'',recent:'all'}
export type MarketFilters=typeof defaultFilters
export function filterStocks(stocks:Stock[],filters:MarketFilters,query:string,scope:string,watchlist:number[],positions:Record<string,Position>,self:number|undefined,now:number){
  const search=query.trim().toLocaleLowerCase()
  const bound=(text:string,value:number,minimum:boolean)=>text.trim()===''||(Number.isFinite(Number(text))&&(minimum?value>=Number(text):value<=Number(text)))
  return stocks.filter(stock=>{
    if(!`${stock.username} ${stock.symbol}`.toLocaleLowerCase().includes(search))return false
    if(scope==='watchlist'&&!watchlist.includes(stock.id)||scope==='positions'&&!positions[stock.id]?.quantity)return false
    if(filters.listing==='listed'&&stock.delisted||filters.listing==='delisted'&&!stock.delisted)return false
    const valid=!stock.stale&&!stock.disabled&&!stock.delisted&&stock.quote.price>0&&stock.id!==self
    if(filters.quote==='valid'&&!valid||filters.quote==='stale'&&!stock.stale||filters.quote==='zero'&&stock.quote.price!==0||filters.quote==='disabled'&&!stock.disabled)return false
    if(filters.ownership==='self'&&stock.id!==self||filters.ownership==='others'&&stock.id===self)return false
    if(!bound(filters.minPrice,stock.quote.price/100,true)||!bound(filters.maxPrice,stock.quote.price/100,false))return false
    const change=stock.open>0?quoteChange(stock.quote.price,stock.open)/10000:null
    if(filters.direction==='rise'&&(change===null||change<=0)||filters.direction==='fall'&&(change===null||change>=0)||filters.direction==='flat'&&change!==0||filters.direction==='unknown'&&change!==null)return false
    if((filters.minChange!==''||filters.maxChange!=='')&&(change===null||!bound(filters.minChange,change,true)||!bound(filters.maxChange,change,false)))return false
    if(filters.recent!=='all'&&(stock.quote.observedAt<=0||now-stock.quote.observedAt>Number(filters.recent)*60))return false
    return true
  })
}
export function sortStocks(stocks:Stock[],sort:string){
  const descending=sort.endsWith('-desc'),field=sort.replace(/-(asc|desc)$/,'')
  return [...stocks].sort((a,b)=>{
    if(field==='change'&&(a.open<=0||b.open<=0)){if(a.open<=0&&b.open>0)return 1;if(b.open<=0&&a.open>0)return -1}
    const diff=field==='name'?a.username.localeCompare(b.username,'zh-CN'):field==='price'?a.quote.price-b.quote.price:field==='change'?quoteChange(a.quote.price,a.open)-quoteChange(b.quote.price,b.open):field==='updated'?a.quote.observedAt-b.quote.observedAt:a.id-b.id
    return (descending?-diff:diff)||a.id-b.id
  })
}
export function positionPnl(position:Position,price:number){return position.quantity>0?position.quantity*price-position.cost:position.cost+position.quantity*price}
