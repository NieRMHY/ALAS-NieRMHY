import {createContext,useContext,useEffect,useState,type ReactNode} from 'react'

export type StockTheme='dark'|'light'
const storageKey='azurpilot.stock-theme'
const Context=createContext<{theme:StockTheme;toggleTheme:()=>void}>({theme:'dark',toggleTheme:()=>{}})

function readTheme():StockTheme {
  try{return localStorage.getItem(storageKey)==='light'?'light':'dark'}catch{return 'dark'}
}

export function StockThemeProvider({children}:{children:ReactNode}){
  const [theme,setTheme]=useState<StockTheme>(readTheme)
  useEffect(()=>{
    try{localStorage.setItem(storageKey,theme)}catch{/* 浏览器禁用存储时，仍可在当前页面切换。 */}
  },[theme])
  return <Context.Provider value={{theme,toggleTheme:()=>setTheme(current=>current==='dark'?'light':'dark')}}>{children}</Context.Provider>
}

export const useStockTheme=()=>useContext(Context)
