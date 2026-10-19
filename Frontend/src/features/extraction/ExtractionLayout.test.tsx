import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ExtractionLayout } from './ExtractionLayout'

function Where() {
  const location = useLocation()
  return <p data-testid="where">{location.pathname + location.search}</p>
}

function renderLayout(path: string, configured = true) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/documents" element={<ExtractionLayout configured={configured} />}>
          <Route index element={<Where />} />
          <Route path="folders/:folderId" element={<Where />} />
          <Route path=":documentId" element={<Where />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

const box = () => screen.getByRole('searchbox', { name: 'Search documents' })

describe('ExtractionLayout search', () => {
  it('puts the typed text in the URL after a short pause, keeping the folder', async () => {
    renderLayout('/documents/folders/abc')

    await userEvent.type(box(), 'invoice 20')

    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('/documents/folders/abc?q=invoice+20'),
    )
    expect(box()).toHaveValue('invoice 20') // typing is never overwritten
  })

  it('searches from the library page when started on another page', async () => {
    renderLayout('/documents/xyz')

    await userEvent.type(box(), 'receipt')

    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/documents?q=receipt'))
  })

  it('shows the URL query on load and clears it with the clear button', async () => {
    renderLayout('/documents?q=scan')
    expect(box()).toHaveValue('scan')

    await userEvent.click(screen.getByRole('button', { name: 'Clear search' }))

    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/documents$/))
    expect(box()).toHaveValue('')
  })
})

describe('ExtractionLayout without a C1 address', () => {
  it('explains how to configure Component 01 instead of showing the pages', () => {
    renderLayout('/documents', false)

    expect(screen.getByText('Component 01 is not configured')).toBeInTheDocument()
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
    expect(screen.queryByTestId('where')).not.toBeInTheDocument()
  })
})
