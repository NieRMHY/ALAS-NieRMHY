import {defineConfig} from '@playwright/test'

// 每次运行隔离账户身份与本地历史日志，避免和正在运行的演示实例互相覆盖。
const runId=`native-e2e-${Date.now()}-${process.pid}`

export default defineConfig({
  testDir:'./e2e/stock-exchange',workers:1,reporter:'list',timeout:60000,
  use:{baseURL:'http://127.0.0.1:5176',headless:true,locale:'zh-CN',viewport:{width:1600,height:1080}},
  webServer:[
    {command:'node ../../AzurPilot_StockExchange/frontend/scripts/dev-mock.mjs',env:{MOCK_API_PORT:'8088',MOCK_FRONTEND_PORT:'5188',MOCK_DATABASE:`data/${runId}.db`},url:'http://127.0.0.1:5188',reuseExistingServer:false,timeout:120000},
    {command:'npm run mock',env:{AZURPILOT_MOCK_PORT:'22592',AZURPILOT_MOCK_STOCK_NAMESPACE:runId,STOCK_EXCHANGE_URL:'http://127.0.0.1:8088'},url:'http://127.0.0.1:22592/healthz',reuseExistingServer:false},
    {command:'npm run dev -- --mode mock --port 5176',env:{AZURPILOT_MOCK_PORT:'22592'},url:'http://127.0.0.1:5176',reuseExistingServer:false},
  ],
})
