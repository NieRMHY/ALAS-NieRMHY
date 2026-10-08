import {useEffect,useMemo,useRef,useState,type KeyboardEvent} from 'react'
import {createPortal} from 'react-dom'
import {init,use,type EChartsType,type EChartsCoreOption} from 'echarts/core'
import {BarChart,CandlestickChart,LineChart} from 'echarts/charts'
import {AxisPointerComponent,DataZoomComponent,GridComponent,MarkLineComponent,TooltipComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'
import {ChevronLeft,ChevronRight,Expand,Minimize2,Minus,Plus,RotateCcw} from 'lucide-react'
import type {Candle,ChartPeriod,StockDetail} from './types'
import {datetime,money} from './api'
import {indicatorLines,indicatorNotes,macd,trend,type Indicator} from './indicators'
import {useStockTheme} from './theme'
import './financial.css'

use([BarChart,CandlestickChart,LineChart,AxisPointerComponent,DataZoomComponent,GridComponent,MarkLineComponent,TooltipComponent,CanvasRenderer])
const emptyBars:Candle[]=[]
export const periods:{value:ChartPeriod;label:string}[]=[{value:'time',label:'分时'},{value:'day',label:'日K'},{value:'m5',label:'M5'},{value:'m10',label:'M10'},{value:'m20',label:'M20'},{value:'m30',label:'M30'},{value:'m60',label:'M60'}]
const chartColors={
  dark:{rise:'#e48886',fall:'#70bba5',grid:'#263340',text:'#80909f',price:'#b9cee0',area:'#94b8cb',previous:'#728476',average:'#e3c382',dea:'#ad9bc9',tooltip:'#1e2a36',tooltipLine:'#4a5b67',tooltipText:'#d9e3e8',pointer:'#708690',zoom:'#111b26',zoomFill:'#839d8738',zoomHandle:'#839d87'},
  light:{rise:'#b6403d',fall:'#147759',grid:'#d8e1db',text:'#5e7168',price:'#2f6992',area:'#548daf',previous:'#78916e',average:'#956610',dea:'#7756a8',tooltip:'#fff',tooltipLine:'#c5d3ca',tooltipText:'#263630',pointer:'#687b72',zoom:'#edf2ef',zoomFill:'#70916038',zoomHandle:'#709160'},
}
const lightIndicatorColors:Record<string,string>={'#e7c482':'#956610','#baa0dc':'#7756a8','#82b9d5':'#2f6992','#dfb176':'#a16020','#aa98d9':'#684ca1','#86b9d1':'#2a718b','#b49cce':'#84579d','#d29ca3':'#a94c60','#8fbea9':'#287a5b','#c8b477':'#896c20','#d5c6a0':'#7e662f'}
const stamp=(t:number,day=false)=>new Date(t).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',...(day?{month:'2-digit',day:'2-digit'}:{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})})
interface Props {detail?:StockDetail;period:ChartPeriod;month:string;day:string;onPeriod:(p:ChartPeriod)=>void;onMonth:(m:string)=>void;onDay:(d:string)=>void;loading:boolean;error:string;large?:boolean}

export function FinancialChart({detail,period,month,day,onPeriod,onMonth,onDay,loading,error,large=false}:Props){
  const {theme}=useStockTheme(),colors=chartColors[theme]
  const [selected,setSelected]=useState<Indicator[]>(['MA']),[sub,setSub]=useState<'volume'|'macd'>('macd'),[full,setFull]=useState(false),[range,setRange]=useState({start:0,end:100}),[help,setHelp]=useState(false)
  const container=useRef<HTMLDivElement>(null),chart=useRef<EChartsType|null>(null),viewport=useRef<{start:number;end:number}|null>(null)
  const bars=detail?.bars??emptyBars,lines=useMemo(()=>indicatorLines(bars,selected).map(line=>({...line,color:theme==='light'?lightIndicatorColors[line.color]??line.color:line.color})),[bars,selected,theme]),oscillator=useMemo(()=>macd(bars),[bars]),signal=useMemo(()=>trend(bars),[bars])
  const identity=`${detail?.stock.id}/${period}/${month}/${day}`
  useEffect(()=>{viewport.current=null},[identity])
  useEffect(()=>{
    if(!full)return
    const old=document.body.style.overflow;document.body.style.overflow='hidden';container.current?.focus()
    const escape=(event:globalThis.KeyboardEvent)=>{if(event.key==='Escape')setFull(false)};document.addEventListener('keydown',escape)
    return ()=>{document.body.style.overflow=old;document.removeEventListener('keydown',escape)}
  },[full])
  useEffect(()=>{
    if(!container.current)return
    const instance=init(container.current,undefined,{renderer:'canvas'});chart.current=instance
    const observer=new ResizeObserver(()=>instance.resize());observer.observe(container.current)
    instance.on('datazoom',()=>{const zoom=instance.getOption().dataZoom as {start:number;end:number}[];if(zoom?.[0]){const next={start:zoom[0].start,end:zoom[0].end};viewport.current=next;setRange(next)}})
    return ()=>{observer.disconnect();instance.dispose();chart.current=null}
  },[full])
  useEffect(()=>{
    const instance=chart.current;if(!instance)return
    const times=bars.map(b=>stamp(b.time,period==='day'))
    const from=Math.max(0,bars.findIndex(b=>b.time>=(detail?.displayFrom??0))),count=period==='time'?bars.length:period==='day'?90:160
    const initial={start:Math.max(from,bars.length-count)/Math.max(1,bars.length-1)*100,end:100},view=viewport.current??initial
    setRange(view)
    const line=(name:string,data:(number|null)[],color:string,index=0,dashed=false)=>({name,type:'line',data:data.map(v=>v??'-'),xAxisIndex:index,yAxisIndex:index,showSymbol:false,connectNulls:false,lineStyle:{color,width:1.25,type:dashed?'dashed':'solid'},itemStyle:{color},emphasis:{disabled:true},animation:false})
    let volume=0,amount=0
    const average=bars.map(b=>{volume+=b.volume;amount+=b.turnover;return volume?amount/volume/100:null})
    const price=period==='time'?{...line('分时价格',bars.map(b=>b.close/100),colors.price),showSymbol:bars.length===1,symbolSize:5,lineStyle:{color:colors.price,width:1.5},areaStyle:{color:colors.area,opacity:.07},markLine:detail?.summary.previousClose?{symbol:'none',silent:true,lineStyle:{color:colors.previous,type:'dashed'},label:{show:false},data:[{yAxis:detail.summary.previousClose/100}]}:undefined}:{name:'K线',type:'candlestick',data:bars.map(b=>[b.open/100,b.close/100,b.low/100,b.high/100]),itemStyle:{color:colors.rise,color0:colors.fall,borderColor:colors.rise,borderColor0:colors.fall},emphasis:{itemStyle:{borderWidth:2}}}
    const series:Record<string,unknown>[]=[price,...(period==='time'?[line('成交均价',average,colors.average)]:[]),...lines.map(l=>line(l.name,l.values,l.color,0,l.dash)),{name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:bars.map(b=>({value:b.volume,itemStyle:{color:b.close>=b.open?colors.rise:colors.fall}})),barMaxWidth:14}]
    if(sub==='macd')series.push({name:'MACD',type:'bar',xAxisIndex:2,yAxisIndex:2,data:oscillator.histogram.map(value=>({value,itemStyle:{color:value>=0?colors.rise:colors.fall}})),barMaxWidth:10},line('DIF',oscillator.dif,colors.average,2),line('DEA',oscillator.dea,colors.dea,2))
    const grids=sub==='macd'?[{left:64,right:18,top:28,bottom:'45%'},{left:64,right:18,top:'64%',height:'8%'},{left:64,right:18,top:'80%',height:'8%'}]:[{left:64,right:18,top:28,bottom:'29%'},{left:64,right:18,top:'79%',height:'9%'}]
    const axes=grids.map((_,i)=>({type:'category',gridIndex:i,data:times,boundaryGap:period!=='time',axisLine:{lineStyle:{color:colors.grid}},axisTick:{show:false},axisLabel:{show:i===grids.length-1,color:colors.text,fontSize:10,hideOverlap:true},axisPointer:{label:{show:true}}}))
    const yAxes=grids.map((_,i)=>({type:'value',gridIndex:i,scale:i===0,splitNumber:i===0?4:2,axisLine:{show:false},axisTick:{show:false},axisLabel:{color:colors.text,fontSize:10,formatter:(value:number)=>i===1?(value>=10000?`${(value/10000).toFixed(1)}万`:String(value)):value.toLocaleString('zh-CN',{maximumFractionDigits:2})},splitLine:{lineStyle:{color:colors.grid,type:'dashed'}},name:i===1?'成交量 / 股':i===2?'MACD(12,26,9)':'价格 / 模拟币',nameGap:12,nameTextStyle:{color:colors.text,fontSize:10,align:'left'}}))
    const option:EChartsCoreOption={animation:false,backgroundColor:'transparent',grid:grids,xAxis:axes,yAxis:yAxes,axisPointer:{link:[{xAxisIndex:'all'}]},tooltip:{trigger:'axis',renderMode:'richText',confine:true,backgroundColor:colors.tooltip,borderColor:colors.tooltipLine,textStyle:{color:colors.tooltipText,fontSize:11},axisPointer:{type:'cross',lineStyle:{color:colors.pointer}},formatter:(params:unknown)=>{const i=(params as {dataIndex:number}[])[0]?.dataIndex,b=bars[i];if(!b)return '';return `${stamp(b.time)}\n开 ${money(b.open)}   高 ${money(b.high)}\n低 ${money(b.low)}   收 ${money(b.close)}\n成交 ${b.volume.toLocaleString()} 股 · ${money(b.turnover)} 模拟币\n${b.samples?`${b.samples} 条行动力观测`:'仅成交记录，尚无新行动力观测'}\n${lines.filter(l=>l.values[i]!==null).map(l=>`${l.name} ${l.values[i]!.toFixed(2)}`).join('  ')}`}},dataZoom:[{type:'inside',xAxisIndex:grids.map((_,i)=>i),start:view.start,end:view.end,filterMode:'none',zoomOnMouseWheel:true,moveOnMouseMove:true,moveOnMouseWheel:false},{type:'slider',xAxisIndex:grids.map((_,i)=>i),start:view.start,end:view.end,filterMode:'none',bottom:2,height:18,borderColor:colors.grid,backgroundColor:colors.zoom,fillerColor:colors.zoomFill,handleStyle:{color:colors.zoomHandle},textStyle:{color:colors.text,fontSize:9},showDataShadow:false}],series}
    instance.setOption(option,{notMerge:true,lazyUpdate:false})
  },[detail,period,lines,oscillator,sub,full,colors])
  function move(action:'in'|'out'|'left'|'right'|'reset'){
    if(!chart.current||bars.length<2)return
    if(action==='reset'){viewport.current=null;const from=Math.max(0,bars.findIndex(b=>b.time>=(detail?.displayFrom??0))),count=period==='time'?bars.length:period==='day'?90:160;const next={start:Math.max(from,bars.length-count)/(bars.length-1)*100,end:100};chart.current.dispatchAction({type:'dataZoom',...next});return}
    const current=viewport.current??range,width=current.end-current.start,min=Math.min(100,5/bars.length*100)
    let span=width,start=current.start,end=current.end
    if(action==='in'||action==='out'){span=Math.max(min,Math.min(100,width*(action==='in'?.7:1.4)));const center=(start+end)/2;start=Math.max(0,Math.min(100-span,center-span/2));end=start+span}else{const offset=width*.25*(action==='left'?-1:1);start=Math.max(0,Math.min(100-width,start+offset));end=start+width}
    chart.current.dispatchAction({type:'dataZoom',start,end})
  }
  function keys(event:KeyboardEvent){if(event.key==='+'||event.key==='='){event.preventDefault();move('in')}else if(event.key==='-'){event.preventDefault();move('out')}else if(event.key==='ArrowLeft'){event.preventDefault();move('left')}else if(event.key==='ArrowRight'){event.preventDefault();move('right')}}
  const first=bars[Math.floor(range.start/100*Math.max(0,bars.length-1))],last=bars[Math.min(bars.length-1,Math.ceil(range.end/100*Math.max(0,bars.length-1)))]
  const content=<section className={`financial-chart ${large?'financial-chart-large':''} ${full?'is-fullscreen':''}`}>
    <div className="financial-chart-top"><div className="chart-periods" role="group" aria-label="走势图周期">{periods.map(p=><button key={p.value} className={period===p.value?'active':''} aria-pressed={period===p.value} onClick={()=>onPeriod(p.value)}>{p.label}</button>)}</div><div className="financial-chart-actions"><button aria-label={full?'退出图表全屏':'全屏走势图'} title={full?'退出全屏 (Esc)':'全屏看图'} onClick={()=>setFull(v=>!v)}>{full?<Minimize2 size={15}/>:<Expand size={15}/>}<span>{full?'退出全屏':'全屏'}</span></button></div></div>
    <div className="indicator-toolbar"><div role="group" aria-label="技术指标">{(['MA','EXPMA','BOLL','ENE','BBI'] as Indicator[]).map(i=><button key={i} aria-pressed={selected.includes(i)} className={selected.includes(i)?'active':''} title={indicatorNotes[i]} onClick={()=>setSelected(old=>old.includes(i)?old.filter(v=>v!==i):[...old,i])}>{i}</button>)}</div><select aria-label="图表副图" value={sub} onChange={e=>setSub(e.target.value as 'volume'|'macd')}><option value="macd">成交量 + MACD</option><option value="volume">成交量</option></select><button className="indicator-help" onClick={()=>setHelp(v=>!v)} aria-expanded={help}>指标说明</button></div>
    <div className="chart-date-toolbar"><label>月份<input type="month" aria-label="行情月份" value={month} onChange={e=>{if(e.target.value)onMonth(e.target.value)}}/></label>{period==='time'&&<label>分时日期<input type="date" aria-label="分时日期" value={day||detail?.day||''} min={`${month}-01`} max={new Date(Number(month.slice(0,4)),Number(month.slice(5)),0).toLocaleDateString('sv-SE')} onChange={e=>onDay(e.target.value)}/></label>}<span className={`trend-label ${signal.direction}`} title={signal.explanation}><i/>{signal.label}</span></div>
    {help&&<div className="indicator-explanation">{selected.map(i=><p key={i}>{indicatorNotes[i]}</p>)}<p>分时黄线为成交加权均价。MACD：DIF = EMA12 − EMA26，DEA = EMA9(DIF)，柱 = 2 × (DIF − DEA)。多空趋势使用 BBI。所有周期按上海时间；M5 / M10 / M20 表示 5 / 10 / 20 分钟。样本不足时不绘制尚未形成的均线；指标为历史统计，不保证未来价格。</p></div>}
    <div className="indicator-legend">{lines.map(l=><span key={l.name} style={{color:l.color}}>{l.name}<b>{l.values.at(-1)?.toFixed(2)??'—'}</b></span>)}</div>
    <div className="financial-canvas-wrap"><div ref={container} className="financial-canvas" role="img" tabIndex={0} aria-label={`${periods.find(p=>p.value===period)?.label}走势图，含成交量${sub==='macd'?'、MACD':''}；滚轮缩放，拖动平移，方向键平移，加减键缩放`} onKeyDown={keys}/>{(loading||!bars.length||error)&&<div className={`financial-chart-state ${error?'chart-error':''}`}>{error?`行情连接中断：${error}`:loading?'正在读取行情…':'此时间段暂无已采集的行情记录'}</div>}</div>
    <div className="chart-navigation"><div><button aria-label="走势图向左平移" title="向左平移" onClick={()=>move('left')}><ChevronLeft size={14}/></button><button aria-label="缩小走势图" title="缩小 (-)" onClick={()=>move('out')}><Minus size={14}/></button><button aria-label="放大走势图" title="放大 (+)" onClick={()=>move('in')}><Plus size={14}/></button><button aria-label="走势图向右平移" title="向右平移" onClick={()=>move('right')}><ChevronRight size={14}/></button><button aria-label="重置走势图" title="重置范围" onClick={()=>move('reset')}><RotateCcw size={13}/></button></div><output role="note" aria-label="图表可视范围" data-start={range.start.toFixed(3)} data-end={range.end.toFixed(3)}>{first&&last?`${stamp(first.time,period==='day')} — ${stamp(last.time,period==='day')}`:'—'}</output><span>滚轮缩放 · 拖动平移 · 双指缩放</span></div>
    <div className="financial-chart-foot"><span>{detail?.coverage.count.toLocaleString()??0} 条月原始记录{detail?.coverage.reconciledAt?` · 校对 ${datetime(detail.coverage.reconciledAt)}`:' · 等待后台校对'}</span><span>观测与实际成交聚合 · 上海时间</span></div>
  </section>
  return full?createPortal(<div className="stock-terminal financial-fullscreen" data-stock-theme={theme} role="dialog" aria-modal="true" aria-label={`${detail?.stock.username??'证券'}全屏走势图`}>{content}</div>,document.body):content
}

export function Sparkline({value,open}:{value:number;open:number}){const up=value>=open;return <svg className="sparkline" viewBox="0 0 76 22" aria-label="今日开盘至最新报价"><path d={open<=0||value===open?'M0 11 L76 11':up?'M0 19 L76 2':'M0 2 L76 19'} fill="none" stroke={up?'var(--mmex-sparkline-rise, #df817f)':'var(--mmex-sparkline-fall, #6bbbaa)'} strokeWidth="1.4"/></svg>}
