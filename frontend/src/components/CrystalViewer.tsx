import {useEffect, useRef, useState} from 'react'
import {Box, RotateCcw, Maximize2} from 'lucide-react'
import type {Crystal} from '../types'

export function CrystalViewer({crystal, compact = false}: {crystal: Crystal|null; compact?: boolean}) {
  const element = useRef<HTMLDivElement>(null)
  const viewer = useRef<import('3dmol').GLViewer | null>(null)
  const [supercell, setSupercell] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    let observer: ResizeObserver|undefined
    setError('')
    if (!crystal || !element.current) return
    const node = element.current
    import('3dmol').then(mol => {
      if (cancelled) return
      node.innerHTML = ''
      const v = mol.createViewer(node, {backgroundColor:'#f5f6fb', antialias:true})
      viewer.current = v
      const model = v.addModel(crystal.cif, 'cif', {doAssembly:true})
      if (supercell) v.replicateUnitCell(2,2,2,model)
      v.setStyle({}, {sphere:{scale:0.25}, stick:{radius:0.085}})
      v.addUnitCell(model, {box:{color:'#9aa6bd'},astyle:{color:'#e16a74'},bstyle:{color:'#56b99e'},cstyle:{color:'#7774dd'}})
      v.zoomTo(); v.rotate(24,'x'); v.rotate(28,'y'); v.render()
      observer = new ResizeObserver(() => { v.resize(); v.render() }); observer.observe(node)
    }).catch(() => { if (!cancelled) setError('三维视图初始化失败，请检查浏览器 WebGL 支持。') })
    return () => {cancelled = true; observer?.disconnect(); viewer.current?.clear(); viewer.current = null; node.innerHTML = ''}
  }, [crystal, supercell])
  return <div className={`crystal-viewer ${compact ? 'compact' : ''}`}>
    <div className="crystal-canvas" ref={element} data-testid="crystal-viewer"/>
    {!crystal && <div className="canvas-placeholder"><Box size={38}/><span>选择材料，探索晶体结构</span></div>}
    {error && <div className="canvas-placeholder">{error}</div>}
    <div className="viewer-label"><span className="status-dot"/> {supercell ? '2 × 2 × 2 超胞' : '原始晶胞'}</div>
    <div className="viewer-tools">
      <button title="切换超胞" aria-label="切换超胞" className={supercell?'active':''} onClick={() => setSupercell(!supercell)}><Box size={15}/></button>
      <button title="重置视角" aria-label="重置视角" onClick={() => {viewer.current?.zoomTo(); viewer.current?.render()}}><RotateCcw size={15}/></button>
      <button title="放大结构" aria-label="放大结构" onClick={() => {viewer.current?.zoom(1.2); viewer.current?.render()}}><Maximize2 size={15}/></button>
    </div>
    <span className="viewer-hint">拖动旋转 · 滚轮缩放</span>
  </div>
}
