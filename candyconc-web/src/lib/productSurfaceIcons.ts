import type { Component } from 'vue'
import {
  BarChart2,
  BookOpen,
  Brain,
  Bookmark,
  Database,
  FileText,
  Hash,
  List,
  Network,
  Scale,
  Settings,
  Share2,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Wand2,
} from 'lucide-vue-next'
import type { ProductSurfaceIconName } from '@/lib/productSurfaceRegistry'

export const productSurfaceIconComponents: Record<ProductSurfaceIconName, Component> = {
  'bar-chart-2': BarChart2,
  'book-open': BookOpen,
  brain: Brain,
  bookmark: Bookmark,
  database: Database,
  'file-text': FileText,
  hash: Hash,
  list: List,
  network: Network,
  scale: Scale,
  settings: Settings,
  'share-2': Share2,
  shield: ShieldCheck,
  sparkles: Sparkles,
  'trending-up': TrendingUp,
  'wand-2': Wand2,
}

export function iconComponentForSurfaceIconName(name: ProductSurfaceIconName): Component {
  return productSurfaceIconComponents[name]
}
