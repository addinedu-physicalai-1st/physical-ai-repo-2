import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import RegisterWizard from '@/components/teacher/RegisterWizard.vue'

function makeWrapper() {
  return mount(RegisterWizard)
}

describe('RegisterWizard', () => {
  it('starts at step 1', () => {
    const w = makeWrapper()
    expect(w.find('[data-test="step1"]').exists()).toBe(true)
    expect(w.find('[data-test="step2"]').exists()).toBe(false)
  })

  it('blocks advancing from step 1 if any field empty', async () => {
    const w = makeWrapper()
    const nextBtn = w.findAll('button').find((b) => b.text().includes('다음'))!
    await nextBtn.trigger('click')
    expect(w.find('[data-test="step1"]').exists()).toBe(true)
  })

  it('advances to step 2 when step 1 fields are filled', async () => {
    const w = makeWrapper()
    const step1 = w.find('[data-test="step1"]')
    const inputs = step1.findAll('input')
    await inputs[0].setValue('김민준')
    await inputs[2].setValue('2021-03-12')
    await step1.find('select').setValue('햇살반')
    const nextBtn = w.findAll('button').find((b) => b.text().includes('다음'))!
    await nextBtn.trigger('click')
    expect(w.find('[data-test="step2"]').exists()).toBe(true)
  })

  it('blocks advancing from step 2 if email format invalid', async () => {
    const w = makeWrapper()
    const step1 = w.find('[data-test="step1"]')
    const s1Inputs = step1.findAll('input')
    await s1Inputs[0].setValue('A')
    await s1Inputs[2].setValue('2021-01-01')
    await step1.find('select').setValue('햇살반')
    const nextBtn = w.findAll('button').find((b) => b.text().includes('다음'))!
    await nextBtn.trigger('click')

    const step2 = w.find('[data-test="step2"]')
    const s2Inputs = step2.findAll('input')
    await s2Inputs[0].setValue('P')
    await s2Inputs[1].setValue('010-0000-0000')
    await s2Inputs[2].setValue('not-an-email')
    const submitBtn = w.findAll('button').find((b) => b.text().includes('등록하기'))!
    await submitBtn.trigger('click')
    expect(w.find('[data-test="step2"]').exists()).toBe(true)
    expect(w.text()).toContain('이메일')
  })

  it('emits submit with combined payload when step 2 valid', async () => {
    const w = makeWrapper()
    const step1 = w.find('[data-test="step1"]')
    const s1Inputs = step1.findAll('input')
    await s1Inputs[0].setValue('김민준')
    await s1Inputs[2].setValue('2021-03-12')
    await step1.find('select').setValue('햇살반')
    const nextBtn = w.findAll('button').find((b) => b.text().includes('다음'))!
    await nextBtn.trigger('click')

    const step2 = w.find('[data-test="step2"]')
    const s2Inputs = step2.findAll('input')
    await s2Inputs[0].setValue('김은혜')
    await s2Inputs[1].setValue('010-1234-5678')
    await s2Inputs[2].setValue('mom@example.com')
    const submitBtn = w.findAll('button').find((b) => b.text().includes('등록하기'))!
    await submitBtn.trigger('click')

    expect(w.emitted('submit')).toBeTruthy()
    const payload = w.emitted('submit')![0][0] as any
    expect(payload.child.name).toBe('김민준')
    expect(payload.child.given_name).toBeNull()
    expect(payload.child.class_name).toBe('햇살반')
    expect(payload.parent.email).toBe('mom@example.com')
    expect(payload.parent.phone).toBe('010-1234-5678')
  })
})
