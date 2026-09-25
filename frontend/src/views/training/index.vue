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

    <p class="roster-line">
      可开班名单（按统一口径自动核对，无需人工比对）：
      <template v-if="roster.length">
        <span v-for="item in roster" :key="String(item.id)" class="roster-tag">
          {{ item['培训编号'] }} · {{ item['培训主题'] }}
        </span>
      </template>
      <span v-else>暂无满足开班条件的培训计划</span>
    </p>

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
type StatItem = { label: string; value: number | string }
type RosterItem = Record<string, string | number | null>

const ENDPOINT = '/api/training'
const columns = ["培训编号", "培训主题", "培训对象", "培训方式", "计划课时", "考核成绩", "培训日期", "培训状态"]
const actions = ["确认开班", "登记结业", "取消培训"]
const statuses = ["待开班", "培训中", "已结业", "已取消"]

// 统计卡片与开班名单都由后端同一份口径算出，前端只展示不自己算，
// 本地演示环境与正式环境看到的才是同一份结果。
const stats = ref<StatItem[]>([
  { label: '待开班培训', value: '—' },
  { label: '培训中课程', value: '—' },
  { label: '平均考核成绩', value: '—' },
])
const roster = ref<RosterItem[]>([])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
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

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 后端会说明是哪一步校验不通过，直接把原因亮出来
      throw new Error(payload.message ?? payload.detail ?? '培训考核动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '培训考核操作失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) {
      throw new Error('培训考核统计读取失败')
    }
    const payload = await response.json()
    stats.value = (payload.stats ?? []).map((item: { label: string; value: number | null }) => ({
      label: item.label,
      value: item.value ?? '—',
    }))
    roster.value = payload['开班名单'] ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '培训考核统计读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('培训计划列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '培训考核列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
