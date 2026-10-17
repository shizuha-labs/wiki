import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { AuthProvider } from './contexts/AuthContext'
import { SpaceProvider } from './contexts/SpaceContext'
import { ToastProvider } from './components/Toast'
import { WIKI_BASE } from './utils/canonicalPage'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={WIKI_BASE} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <SpaceProvider>
            <ToastProvider>
              <App />
            </ToastProvider>
          </SpaceProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
