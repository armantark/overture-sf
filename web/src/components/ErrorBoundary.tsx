import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

// A bad row must degrade to a readable message, never a blank page.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="boundary-error" role="alert">
          <p className="empty-title">This view hit an unexpected error.</p>
          <p className="boundary-error-detail">{this.state.error.message}</p>
          <button
            type="button"
            className="tab"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
