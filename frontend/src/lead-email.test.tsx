import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { EmailTypeControl } from './EmailTypeControl'
import { inferEmailType } from './lead-email'

describe('inferEmailType', () => {
  it.each(['person@gmail.com', 'person@YAHOO.CO.IN', ' person@proton.me '])('%s is classified as personal', email => {
    expect(inferEmailType(email)).toBe('personal')
  })

  it.each(['person@latentsig.com', 'person@example.co.in', 'invalid-address'])('%s defaults to work', email => {
    expect(inferEmailType(email)).toBe('work')
  })
})

describe('EmailTypeControl', () => {
  it('shows and changes the selected email type accessibly', () => {
    const onChange = vi.fn()
    render(<EmailTypeControl value="work" onChange={onChange} />)
    expect(screen.getByRole('radio', { name: 'Work' })).toBeChecked()
    fireEvent.click(screen.getByRole('radio', { name: 'Personal' }))
    expect(onChange).toHaveBeenCalledWith('personal')
  })
})
