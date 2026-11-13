<template>
  <div class="min-h-screen py-16 px-4">
    <div class="max-w-2xl mx-auto">
      <h1 class="text-2xl font-semibold text-gray-900">Verify an NRS e-invoice</h1>
      <p class="mt-2 text-sm text-gray-600">
        Paste the IRN printed on the invoice, or the full QR payload string if your
        scanner app shows one.
      </p>

      <div class="mt-6 bg-white rounded-lg border border-gray-200 p-6">
        <Textarea
          v-model="value"
          label="IRN or QR payload"
          placeholder="SINV-00584-31A9D784-20261111"
          :rows="3"
        />
        <div class="mt-4 flex items-center gap-3">
          <Button variant="solid" :loading="loading" @click="submit">Verify</Button>
          <Button variant="subtle" @click="reset">Clear</Button>
        </div>
      </div>

      <div
        v-if="error"
        class="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
      >
        {{ error }}
      </div>

      <div v-if="result" class="mt-6 bg-white rounded-lg border border-gray-200 p-6">
        <div class="flex items-center gap-2">
          <span
            class="inline-block h-2.5 w-2.5 rounded-full"
            :class="result.valid ? 'bg-green-500' : 'bg-amber-500'"
          ></span>
          <span class="font-medium text-gray-900">{{ result.headline }}</span>
        </div>
        <dl class="mt-4 grid grid-cols-1 gap-3 text-sm">
          <div v-for="row in rows" :key="row.label" class="flex gap-3">
            <dt class="w-44 shrink-0 text-gray-500">{{ row.label }}</dt>
            <dd class="text-gray-900 break-all">{{ row.value }}</dd>
          </div>
        </dl>
        <p v-if="result.note" class="mt-4 text-xs text-gray-500">{{ result.note }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Button, Textarea } from 'frappe-ui'

const value = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null)

const rows = computed(() => {
  if (!result.value) return []
  return Object.entries(result.value.fields || {})
    .filter(([, v]) => v)
    .map(([label, v]) => ({ label, value: v }))
})

async function submit() {
  const text = value.value.trim()
  if (!text) {
    error.value = 'Paste an IRN or QR payload first.'
    return
  }
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const url = '/api/method/theoskaris_einvoice.api.verify.validate?value=' +
      encodeURIComponent(text)
    const res = await fetch(url)
    const body = await res.json()
    if (!res.ok) {
      throw new Error(body._error_message || body.exception || 'Verification failed')
    }
    result.value = body.message
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function reset() {
  value.value = ''
  result.value = null
  error.value = ''
}
</script>
