import {Component,type ReactNode} from 'react'
import {Link,useParams} from 'react-router-dom'
import {ArrowLeft} from 'lucide-react'
import {Loading} from '../components/ui'
import {StockThemeProvider,useStockTheme} from './theme'
import './styles.css'
import '../pages/stock-exchange.css'
import './theme.css'

export function OverviewLink({instance}:{instance:string}){
  return <Link className="overview-link" to={`/i/${encodeURIComponent(instance)}/overview`} title="返回当前实例的运行总览"><ArrowLeft size={15}/><span>返回总览</span></Link>
}

function FallbackContent({message}:{message?:string}){
  const {instance=''}=useParams(),{theme}=useStockTheme()
  return <div className="stock-terminal stock-exchange-loading" data-stock-theme={theme}>{message?<p role="alert">{message}</p>:<Loading/>}<OverviewLink instance={instance}/></div>
}

export function StockExchangeFallback({message}:{message?:string}){
  return <StockThemeProvider><FallbackContent message={message}/></StockThemeProvider>
}

class TerminalBoundary extends Component<{children:ReactNode},{failed:boolean}>{
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  render(){return this.state.failed?<StockExchangeFallback message="交易页面加载失败，请返回总览后重试。"/>:this.props.children}
}

export function StockExchangeBoundary({children}:{children:ReactNode}){
  const {instance}=useParams()
  return <TerminalBoundary key={instance}>{children}</TerminalBoundary>
}
