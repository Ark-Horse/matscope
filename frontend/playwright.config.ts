import {defineConfig} from '@playwright/test'
export default defineConfig({testDir:'./e2e',timeout:60000,workers:1,use:{baseURL:'http://127.0.0.1:8000',channel:process.env.CI?undefined:'chrome',viewport:{width:1440,height:1080},screenshot:'only-on-failure',launchOptions:{args:['--use-angle=swiftshader','--enable-webgl','--enable-unsafe-swiftshader']}}})
