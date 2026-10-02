import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import {ImageDown} from 'lucide-react'

export function Chart({option, height = 310, onClick, label}: {option: EChartsOption; height?: number; onClick?: (data: unknown) => void; label: string}) {
  const element = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  useEffect(() => {
    if (!element.current) return
    chart.current = echarts.init(element.current, undefined, {renderer:'canvas'})
    const observer = new ResizeObserver(() => chart.current?.resize()); observer.observe(element.current)
    return () => { observer.disconnect(); chart.current?.dispose(); chart.current = null }
  }, [])
  useEffect(() => { chart.current?.setOption(option, true) }, [option])
  useEffect(() => {
    const current = chart.current
    if (!current || !onClick) return
    const handler = (params: unknown) => onClick(params)
    current.on('click', handler)
    return () => {current.off('click', handler)}
  }, [onClick])
  return <div className="chart-wrapper"><div className="chart" ref={element} style={{height}} role="img" aria-label={label}/><button className="chart-export" aria-label={`导出图像：${label}`} title="导出 PNG 图片" onClick={()=>{if(!chart.current)return;const a=document.createElement('a');a.href=chart.current.getDataURL({type:'png',pixelRatio:2,backgroundColor:'#fff'});a.download=`${label}.png`;a.click()}}><ImageDown size={14}/></button></div>
}

export const axis = {axisLine:{show:false},axisTick:{show:false},axisLabel:{color:'#8a93a5',fontSize:11},splitLine:{lineStyle:{color:'#edf0f5',type:'dashed' as const}},nameTextStyle:{color:'#8a93a5',fontSize:11}}
export const tooltip = {backgroundColor:'#fff',borderColor:'#e5e8f1',textStyle:{color:'#29354d'},extraCssText:'box-shadow:0 6px 24px #24344c12;border-radius:10px;'}
