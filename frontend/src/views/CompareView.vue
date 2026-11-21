<script setup>
import { ref } from 'vue'
import { searchCars, getCarDetail } from '../api'

const keyword = ref('')
const searchResults = ref([])
const selected = ref([])
const compareData = ref(null)

async function doSearch() {
  if (!keyword.value.trim()) return
  const res = await searchCars({ keyword: keyword.value, limit: 20 })
  searchResults.value = res.cars
}

function toggleSelect(car) {
  const idx = selected.value.findIndex(c => c.车型ID === car.车型ID)
  if (idx >= 0) {
    selected.value.splice(idx, 1)
  } else if (selected.value.length < 5) {
    selected.value.push(car)
  }
}

async function doCompare() {
  if (selected.value.length < 2) return
  const ids = selected.value.map(c => c.车型ID)
  // 使用后端 compare 逻辑：逐个取详情后对比
  const details = await Promise.all(ids.map(id => getCarDetail(id)))
  const keyFields = ['品牌','车系','车型款','指导价','级别','能源类型','上市时间','发动机','变速箱','长×宽×高(mm)','轴距(mm)','发动机最大马力(Ps)','WLTC综合油耗(L/100km)','驱动方式','座位数(个)']
  compareData.value = { fields: keyFields, models: details }
}

function clearAll() {
  selected.value = []
  compareData.value = null
  searchResults.value = []
  keyword.value = ''
}
</script>

<template>
  <div class="compare-page">
    <div class="search-bar">
      <input v-model="keyword" @keyup.enter="doSearch" placeholder="搜索车型名称（如 奥迪A4L、宝马3系）" />
      <button @click="doSearch">搜索</button>
      <button class="clear" @click="clearAll">清空</button>
    </div>

    <div class="search-results" v-if="searchResults.length">
      <div class="hint">点击选择 2~5 款车型进行对比（已选 {{ selected.length }}）</div>
      <div class="result-list">
        <div v-for="car in searchResults" :key="car.车型ID" class="result-item"
             :class="{ selected: selected.some(c => c.车型ID === car.车型ID) }"
             @click="toggleSelect(car)">
          <div class="r-name">{{ car.车型款 }}</div>
          <div class="r-price">{{ car.指导价 }}</div>
        </div>
      </div>
    </div>

    <div class="selected-bar" v-if="selected.length >= 2">
      <span>已选 {{ selected.length }} 款</span>
      <button @click="doCompare">开始对比</button>
    </div>

    <div class="compare-table" v-if="compareData">
      <table>
        <thead>
          <tr>
            <th class="field-col">参数</th>
            <th v-for="m in compareData.models" :key="m.车型ID">{{ m.车型款 }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in compareData.fields" :key="f">
            <td class="field-name">{{ f }}</td>
            <td v-for="m in compareData.models" :key="m.车型ID + f">{{ m[f] || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.compare-page { padding: 24px; }
.search-bar { display: flex; gap: 10px; margin-bottom: 20px; }
.search-bar input { flex: 1; padding: 10px 14px; border: 1px solid #d9d9d9; border-radius: 8px; }
.search-bar button { padding: 10px 20px; background: #0f3460; color: #fff; border: none; border-radius: 8px; cursor: pointer; }
.search-bar button.clear { background: #999; }
.hint { color: #666; margin-bottom: 12px; font-size: 14px; }
.result-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.result-item { background: #fff; padding: 12px; border-radius: 8px; cursor: pointer; border: 2px solid transparent; }
.result-item:hover { border-color: #1890ff; }
.result-item.selected { border-color: #52c41a; background: #f6ffed; }
.r-name { font-weight: 600; margin-bottom: 6px; }
.r-price { color: #e94560; }
.selected-bar { position: sticky; top: 0; background: #fff; padding: 12px; margin: 16px 0; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.1); display: flex; justify-content: space-between; align-items: center; }
.selected-bar button { padding: 8px 20px; background: #52c41a; color: #fff; border: none; border-radius: 6px; cursor: pointer; }
.compare-table { overflow-x: auto; }
.compare-table table { width: 100%; border-collapse: collapse; background: #fff; }
.compare-table th, .compare-table td { padding: 10px 12px; border: 1px solid #e0e0e0; text-align: left; font-size: 13px; }
.compare-table th { background: #fafafa; font-weight: 600; }
.field-col, .field-name { background: #fafafa; font-weight: 600; color: #555; }
</style>
