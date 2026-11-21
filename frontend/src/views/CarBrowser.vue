<script setup>
import { ref, onMounted } from 'vue'
import { getBrands, getSeries, searchCars } from '../api'

const brands = ref([])
const selectedBrand = ref('')
const series = ref([])
const selectedSeries = ref('')
const cars = ref([])
const detailCar = ref(null)

onMounted(async () => {
  const res = await getBrands()
  brands.value = res.brands
})

async function selectBrand(brand) {
  selectedBrand.value = brand
  const res = await getSeries(brand)
  series.value = res.series
  cars.value = []
}

async function selectSeries(s) {
  selectedSeries.value = s.series_name
  const res = await searchCars({ brand: selectedBrand.value, series: s.series_name, limit: 50 })
  cars.value = res.cars
}

async function viewDetail(car) {
  const res = await import('../api').then(m => m.getCarDetail(car.车型ID))
  detailCar.value = res
}

function closeDetail() { detailCar.value = null }
</script>

<template>
  <div class="browser">
    <div class="brand-list">
      <div class="section-title">品牌 ({{ brands.length }})</div>
      <div class="brand-items">
        <div v-for="b in brands" :key="b.brand" class="brand-item"
             :class="{ active: selectedBrand === b.brand }" @click="selectBrand(b.brand)">
          {{ b.brand }} <span class="count">{{ b.series_count }}</span>
        </div>
      </div>
    </div>

    <div class="series-list" v-if="series.length">
      <div class="section-title">车系 - {{ selectedBrand }}</div>
      <div class="series-items">
        <div v-for="s in series" :key="s.series_id" class="series-item"
             :class="{ active: selectedSeries === s.series_name }" @click="selectSeries(s)">
          {{ s.series_name }}
        </div>
      </div>
    </div>

    <div class="car-list" v-if="cars.length">
      <div class="section-title">车型 ({{ cars.length }})</div>
      <div class="car-grid">
        <div v-for="car in cars" :key="car.车型ID" class="car-card" @click="viewDetail(car)">
          <div class="car-name">{{ car.车型款 }}</div>
          <div class="car-price">{{ car.指导价 }}</div>
          <div class="car-meta">{{ car.级别 }} / {{ car.能源类型 }}</div>
        </div>
      </div>
    </div>

    <div class="detail-modal" v-if="detailCar" @click.self="closeDetail">
      <div class="detail-content">
        <button class="close-btn" @click="closeDetail">×</button>
        <h2>{{ detailCar.车型款 }}</h2>
        <div class="detail-price">指导价: {{ detailCar.指导价 }}</div>
        <table class="detail-table">
          <tr v-for="(v, k) in detailCar" :key="k" v-if="v !== null && v !== ''">
            <td class="key">{{ k }}</td>
            <td class="val">{{ v }}</td>
          </tr>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.browser { display: flex; height: 100%; }
.brand-list { width: 180px; border-right: 1px solid #e0e0e0; overflow-y: auto; padding: 16px; background: #fff; }
.series-list { width: 200px; border-right: 1px solid #e0e0e0; overflow-y: auto; padding: 16px; background: #fafafa; }
.car-list { flex: 1; overflow-y: auto; padding: 16px; }
.section-title { font-weight: 600; margin-bottom: 12px; color: #333; }
.brand-item, .series-item { padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 14px; margin-bottom: 4px; }
.brand-item:hover, .series-item:hover { background: #f0f0f0; }
.brand-item.active, .series-item.active { background: #0f3460; color: #fff; }
.count { font-size: 12px; opacity: .6; }
.car-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.car-card { background: #fff; padding: 16px; border-radius: 8px; cursor: pointer; border: 1px solid #e0e0e0; transition: all .2s; }
.car-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.1); transform: translateY(-2px); }
.car-name { font-weight: 600; margin-bottom: 8px; }
.car-price { color: #e94560; font-size: 18px; font-weight: 600; margin-bottom: 6px; }
.car-meta { font-size: 12px; color: #999; }
.detail-modal { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.detail-content { background: #fff; padding: 24px; border-radius: 12px; max-width: 800px; max-height: 80vh; overflow-y: auto; position: relative; }
.close-btn { position: absolute; top: 12px; right: 16px; font-size: 24px; background: none; border: none; cursor: pointer; }
.detail-price { font-size: 20px; color: #e94560; margin: 12px 0; }
.detail-table { width: 100%; border-collapse: collapse; }
.detail-table td { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.detail-table .key { width: 40%; color: #666; background: #fafafa; }
</style>
