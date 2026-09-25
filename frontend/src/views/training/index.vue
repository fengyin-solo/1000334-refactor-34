<template>
  <section class="page" data-module="training">
    <header class="page-head">
      <div>
        <h2>培训考核管理</h2>
        <p class="page-desc">维护培训计划，围绕培训编号、培训主题、培训对象、培训方式做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记培训计划</button>
        <button class="btn" type="button" @click="exportRows">导出培训考核清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无培训考核数据，可先登记培训计划</td>
        </tr>
      </tbody>
    </table>

    <ul v-if="checkDetails.length" class="check-list">
      <li
        v-for="item in checkDetails"
        :key="item.step"
        :class="item.ok ? 'check-pass' : 'check-fail'"
      >
        {{ item.ok ? '✓' : '✗' }} {{ item.step }}：{{ item.message }}
      </li>
    </ul>

    <footer class="page-foot">
      <span>共 {{ total }} 条培训考核记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface CheckItem {
  step: string
  ok: boolean
  message: string
}

interface ActionPayload {
  ok?: boolean
  message?: string
  detail?: string
  checks?: CheckItem[]
}

const ENDPOINT = '/api/training'
const columns = ["培训编号", "培训主题", "培训对象", "培训方式", "计划课时", "考核成绩", "培训日期", "培训状态", "开班名单", "结业结果"]
const actions = ["确认开班", "登记结业", "取消培训"]

// 统计卡完全以后端 /summary 的同一份口径为准，前端不再各自计算
const stats = ref([
  { label: '待开班培训', value: '—' },
  { label: '培训中课程', value: '—' },
  { label: '平均考核成绩', value: '—' },
  { label: '考核口径版本', value: '—' },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const checkDetails = ref<CheckItem[]>([])
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '培训计划登记入口尚未接入审批流'
}

// 仅用于决定要不要提示补录成绩；是否有效仍以服务端口径为准
function looksLikeScore(value: unknown): boolean {
  if (typeof value === 'number') return value >= 0 && value <= 100
  if (typeof value !== 'string') return false
  const text = value.trim().replace(/[分%]$/, '')
  if (!/^\d+(\.\d+)?$/.test(text)) return false
  const num = Number(text)
  return num >= 0 && num <= 100
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  checkDetails.value = []
  const values: Record<string, unknown> = { action }
  if (action === '登记结业' && !looksLikeScore(row['考核成绩'])) {
    const input = window.prompt(`请输入「${row['培训主题'] ?? row.id}」的考核成绩（0-100）`)
    if (input === null) return
    values['考核成绩'] = input
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = (await response.json()) as ActionPayload
    checkDetails.value = payload.checks ?? []
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message ?? payload.detail ?? '培训考核动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '培训考核操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [listResponse, summaryResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/summary`),
    ])
    if (!listResponse.ok) {
      throw new Error('培训计划列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (summaryResponse.ok) {
      const summary = await summaryResponse.json()
      stats.value = [
        { label: '待开班培训', value: String(summary['待开班培训'] ?? 0) },
        { label: '培训中课程', value: String(summary['培训中课程'] ?? 0) },
        { label: '平均考核成绩', value: summary['平均考核成绩'] ?? '—' },
        { label: '考核口径版本', value: summary['口径版本'] ?? '—' },
      ]
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '培训考核列表读取失败'
  }
}

onMounted(reload)
</script>
