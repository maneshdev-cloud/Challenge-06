import { AlertOctagon, PhoneCall, X } from "lucide-react";

export default function EmergencyBanner({ message, onDismiss }) {
  if (!message) return null;

  return (
    <div
      role="alert"
      className="rounded-2xl border-2 border-red-600 bg-red-50 p-4 text-red-950 shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-red-600 text-white">
            <AlertOctagon className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-extrabold uppercase tracking-wide text-red-900">
                Urgent Medical Triage Intercepted
              </h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-red-700 px-2.5 py-0.5 text-xs font-bold text-white">
                <PhoneCall className="h-3 w-3" aria-hidden="true" />
                <span>
                  Call{" "}
                  <a href="tel:108" className="underline underline-offset-2 hover:text-red-100">
                    108
                  </a>{" "}
                  /{" "}
                  <a href="tel:112" className="underline underline-offset-2 hover:text-red-100">
                    112
                  </a>{" "}
                  (India ER)
                </span>
              </span>
            </div>
            <p className="mt-1.5 text-sm font-medium leading-relaxed text-red-900">{message}</p>
          </div>
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss emergency banner"
            className="rounded-lg p-1 text-red-700 hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-600"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );
}
