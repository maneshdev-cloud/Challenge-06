import React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      errorMessage: error?.message || "Unexpected rendering error."
    };
  }

  handleReload = () => {
    this.setState({ hasError: false, errorMessage: "" });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="mx-auto my-12 max-w-lg rounded-3xl bg-white p-6 text-slate-800 shadow-lg ring-1 ring-rose-200"
        >
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-6 w-6 shrink-0 text-rose-600" aria-hidden="true" />
            <div>
              <h1 className="text-base font-extrabold text-slate-900">
                PRANA-AI encountered a display error
              </h1>
              <p className="mt-1 text-xs text-slate-600">
                {this.state.errorMessage}
              </p>
              <button
                type="button"
                onClick={this.handleReload}
                className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-teal-700 px-4 py-2 text-xs font-bold text-white transition hover:bg-teal-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                Reset View
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
