<script setup lang="ts">
/**
 * LineChart - D3-based line chart for trend/diachrony series.
 *
 * X = Periode (kategorial, chronologisch sortiert geliefert), Y = pro Million.
 * Rendert das Wilson-Konfidenzintervall (ciLow/ciHigh) als Band hinter der
 * Linie und zeigt je Punkt einen Tooltip mit Periode, Treffern, Tokens,
 * pro-Million-Rate und CI-Grenzen. Theme über CSS-Variablen wie BarChart.
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as d3 from 'd3'
import { currentLocale } from '@/i18n/locale'
import { localeD3Format } from '@/i18n/d3Format'
import { formatInterval, formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

export interface LineChartPoint {
  /** Periodenlabel (z.B. '2021' oder '2021-04'). */
  label: string
  /** Rate pro Million Tokens. */
  value: number
  /** CI-Untergrenze (pro Million). */
  ciLow: number
  /** CI-Obergrenze (pro Million). */
  ciHigh: number
  /** Absolute Treffer in der Periode. */
  hits: number
  /** Token-Basis der Periode. */
  tokens: number
}

interface Props {
  data: LineChartPoint[]
  height?: number
  /** Points react to a click (event pointClick) and show a pointer. */
  clickable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  height: 320,
  clickable: false,
})

const emit = defineEmits<{ pointClick: [point: LineChartPoint] }>()

const { t } = useI18n()
const containerRef = ref<HTMLDivElement | null>(null)
const tooltip = ref<{
  visible: boolean
  x: number
  y: number
  point: LineChartPoint | null
}>({ visible: false, x: 0, y: 0, point: null })

let resizeObserver: ResizeObserver | null = null

const nf = (value: number, digits = 0) =>
  formatNumber(value, { minimumFractionDigits: digits, maximumFractionDigits: digits })

function render() {
  if (!containerRef.value) return
  const container = containerRef.value
  const svgHost = container.querySelector('.line-chart-svg-host') as HTMLDivElement | null
  if (!svgHost) return
  svgHost.innerHTML = ''
  if (!props.data.length) return

  const margin = { top: 16, right: 24, bottom: 64, left: 64 }
  const width = container.clientWidth - margin.left - margin.right
  const height = props.height - margin.top - margin.bottom

  if (width <= 0 || height <= 0) return

  const svg = d3.select(svgHost)
    .append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  const labels = props.data.map((d) => d.label)
  const x = d3.scalePoint<string>()
    .domain(labels)
    .range([0, width])
    .padding(0.5)

  const yMax = d3.max(props.data, (d) => Math.max(d.ciHigh, d.value)) || 0
  const y = d3.scaleLinear()
    .domain([0, yMax])
    .nice()
    .range([height, 0])

  // X axis: thin ticks when many periods so the labels stay readable.
  const tickEvery = Math.max(1, Math.ceil(labels.length / 24))
  const xAxis = d3.axisBottom(x)
    .tickValues(labels.filter((_, i) => i % tickEvery === 0))
  svg.append('g')
    .attr('transform', `translate(0,${height})`)
    .call(xAxis)
    .selectAll('text')
    .attr('transform', 'rotate(-45)')
    .style('text-anchor', 'end')
    .attr('dx', '-.8em')
    .attr('dy', '.15em')

  // Y axis
  svg.append('g')
    .call(d3.axisLeft(y).ticks(6).tickFormat(localeD3Format(',.0f')))

  // Y axis caption
  svg.append('text')
    .attr('class', 'axis-caption')
    .attr('transform', 'rotate(-90)')
    .attr('x', -height / 2)
    .attr('y', -margin.left + 14)
    .attr('text-anchor', 'middle')
    .text(t('analysis.charts.hitsPerMillion'))

  // Confidence band (Wilson interval, pro Million)
  const area = d3.area<LineChartPoint>()
    .x((d) => x(d.label) ?? 0)
    .y0((d) => y(d.ciLow))
    .y1((d) => y(d.ciHigh))

  svg.append('path')
    .datum(props.data)
    .attr('class', 'ci-band')
    .attr('fill', 'var(--color-primary-500)')
    .attr('fill-opacity', 0.15)
    .attr('stroke', 'none')
    .attr('d', area)

  // Main line
  const line = d3.line<LineChartPoint>()
    .x((d) => x(d.label) ?? 0)
    .y((d) => y(d.value))

  svg.append('path')
    .datum(props.data)
    .attr('class', 'trend-line')
    .attr('fill', 'none')
    .attr('stroke', 'var(--color-primary-500)')
    .attr('stroke-width', 2)
    .attr('d', line)

  // Points with tooltip
  svg.selectAll('.trend-point')
    .data(props.data)
    .enter()
    .append('circle')
    .attr('class', 'trend-point')
    .attr('cx', (d: LineChartPoint) => x(d.label) ?? 0)
    .attr('cy', (d: LineChartPoint) => y(d.value))
    .attr('r', 3.5)
    .attr('fill', 'var(--color-primary-500)')
    .attr('stroke', 'var(--color-primary-600)')
    .on('mouseover', function (_event: MouseEvent, d: LineChartPoint) {
      d3.select(this).attr('r', 5)
      const px = (x(d.label) ?? 0) + margin.left
      const py = y(d.value) + margin.top
      tooltip.value = { visible: true, x: px, y: py, point: d }
    })
    .on('mouseout', function () {
      d3.select(this).attr('r', 3.5)
      tooltip.value = { visible: false, x: 0, y: 0, point: null }
    })
    .style('cursor', props.clickable ? 'pointer' : 'default')
    .on('click', (_event: MouseEvent, d: LineChartPoint) => {
      if (props.clickable) emit('pointClick', d)
    })
}

onMounted(() => {
  nextTick(render)

  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      render()
    })
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
})

watch(() => props.data, render, { deep: true })
// Axis and label numbers follow the interface language.
watch(() => currentLocale(), render)
watch(() => props.height, render)
</script>

<template>
  <div ref="containerRef" class="line-chart">
    <div class="line-chart-svg-host" />
    <div
      v-if="tooltip.visible && tooltip.point"
      class="line-chart-tooltip"
      :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }"
      role="status"
    >
      <div class="tooltip-title">{{ tooltip.point.label }}</div>
      <dl class="tooltip-grid">
        <dt>{{ t('analysis.charts.hits') }}</dt>
        <dd>{{ nf(tooltip.point.hits) }}</dd>
        <dt>{{ t('analysis.charts.tokens') }}</dt>
        <dd>{{ nf(tooltip.point.tokens) }}</dd>
        <dt>{{ t('analysis.charts.perMillion') }}</dt>
        <dd>{{ nf(tooltip.point.value, 2) }}</dd>
        <dt>{{ t('analysis.charts.ci95') }}</dt>
        <dd>{{ formatInterval(tooltip.point.ciLow, tooltip.point.ciHigh, 2) }}</dd>
      </dl>
      <div v-if="clickable" class="tooltip-hint">{{ t('analysis.charts.openPointHint') }}</div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.line-chart {
  @apply relative w-full min-h-[200px];
}

.line-chart :deep(text) {
  @apply fill-neutral-600 dark:fill-neutral-400;
  font-size: 12px;
}

.line-chart :deep(.axis-caption) {
  @apply fill-neutral-500 dark:fill-neutral-400;
  font-size: 11px;
}

.line-chart :deep(.domain),
.line-chart :deep(.tick line) {
  @apply stroke-neutral-300 dark:stroke-neutral-600;
}

.line-chart-tooltip {
  @apply pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full;
  @apply rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs shadow-lg;
  @apply dark:border-neutral-700 dark:bg-neutral-900;
  margin-top: -10px;
  min-width: 10rem;
}

.tooltip-title {
  @apply mb-1 font-semibold text-neutral-900 dark:text-neutral-100;
}

.tooltip-hint {
  @apply mt-1 text-[11px] text-neutral-500 dark:text-neutral-400;
}

.tooltip-grid {
  @apply grid gap-x-3 gap-y-0.5;
  grid-template-columns: max-content 1fr;
}

.tooltip-grid dt {
  @apply text-neutral-500 dark:text-neutral-400;
}

.tooltip-grid dd {
  @apply text-right font-mono text-neutral-800 dark:text-neutral-200;
}
</style>
