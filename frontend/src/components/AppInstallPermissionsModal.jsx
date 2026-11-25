import React, { useEffect, useState } from "react";
import {
  Camera,
  CheckCircle2,
  Download,
  MapPin,
  Mic,
  PlusSquare,
  Share,
  ShieldCheck,
  Smartphone,
  X,
  AlertTriangle
} from "lucide-react";
import {
  detectPlatform,
  requestCameraAccess,
  requestMicrophoneAccess,
  testAllPhonePermissions
} from "../utils/pwaAndPermissions";

function StatusBadge({ status }) {
  if (status === "granted") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-[11px] font-bold text-emerald-800">
        <CheckCircle2 className="h-3 w-3" /> Allowed
      </span>
    );
  }
  if (status === "denied") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2.5 py-0.5 text-[11px] font-bold text-rose-800">
        <AlertTriangle className="h-3 w-3" /> Blocked
      </span>
    );
  }
  if (status === "insecure_context") {
    return (
      <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-bold text-amber-900">
        Needs HTTPS
      </span>
    );
  }
  if (status === "unsupported") {
    return (
      <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-bold text-slate-600">
        Unavailable
      </span>
    );
  }
  return (
    <span className="rounded-full bg-sky-100 px-2.5 py-0.5 text-[11px] font-bold text-sky-900">
      Tap to Allow
    </span>
  );
}

export default function AppInstallPermissionsModal({
  open,
  onClose,
  canPromptInstall,
  onTriggerNativeInstall,
  onRequestLocation
}) {
  const [platform, setPlatform] = useState({ isIOS: false, isAndroid: false, isMobile: false, isStandalone: false });
  const [perms, setPerms] = useState({ location: "prompt", microphone: "prompt", camera: "prompt" });
  const [feedback, setFeedback] = useState(null);
  const [busyPerm, setBusyPerm] = useState(null);

  useEffect(() => {
    if (!open) return;
    setPlatform(detectPlatform());
    setFeedback(null);
    testAllPhonePermissions().then(setPerms).catch(() => {});
  }, [open]);

  if (!open) return null;

  async function handleEnableMic() {
    setBusyPerm("microphone");
    const res = await requestMicrophoneAccess();
    setFeedback(res.message);
    const updated = await testAllPhonePermissions();
    setPerms({ ...updated, microphone: res.state === "granted" ? "granted" : updated.microphone === "prompt" && res.state === "denied" ? "denied" : updated.microphone });
    setBusyPerm(null);
  }

  async function handleEnableCamera() {
    setBusyPerm("camera");
    const res = await requestCameraAccess();
    setFeedback(res.message);
    const updated = await testAllPhonePermissions();
    setPerms({ ...updated, camera: res.state === "granted" ? "granted" : updated.camera === "prompt" && res.state === "denied" ? "denied" : updated.camera });
    setBusyPerm(null);
  }

  function handleEnableLocation() {
    setBusyPerm("location");
    setFeedback("Triggering browser GPS permission prompt...");
    onRequestLocation?.();
    setTimeout(() => {
      testAllPhonePermissions().then(setPerms).catch(() => {});
      setBusyPerm(null);
    }, 1500);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/55 p-4 backdrop-blur-sm">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-3xl bg-white p-5 shadow-2xl ring-1 ring-slate-200 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-teal-50 text-teal-700">
              <Smartphone className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-extrabold text-slate-900">Install App &amp; Phone Permissions</h2>
              <p className="text-xs text-slate-500">Works on Android Chrome, iOS Safari &amp; Desktop</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            className="rounded-xl p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* PWA Install Section */}
        <div className="mt-5 rounded-2xl bg-gradient-to-br from-slate-900 to-teal-900 p-4 text-white">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-teal-300">
                Mobile Home-Screen App
              </span>
              <h3 className="mt-0.5 text-sm font-extrabold">
                {platform.isStandalone ? "PRANA-AI is installed" : "Add PRANA-AI to your phone"}
              </h3>
            </div>
            {canPromptInstall && !platform.isStandalone && (
              <button
                type="button"
                onClick={async () => {
                  const outcome = await onTriggerNativeInstall?.();
                  if (outcome === "accepted") {
                    setFeedback("PRANA-AI installed! Open it anytime from your home screen.");
                  }
                }}
                className="inline-flex items-center gap-1.5 rounded-full bg-emerald-400 px-3.5 py-1.5 text-xs font-extrabold text-slate-950 transition hover:bg-emerald-300"
              >
                <Download className="h-3.5 w-3.5" />
                Install Now
              </button>
            )}
          </div>

          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div className="rounded-xl bg-white/10 p-3 text-xs">
              <p className="font-bold text-teal-200">Android (Chrome / Edge)</p>
              <p className="mt-1 text-slate-200">
                Tap <strong>Install Now</strong> above or open browser menu &rarr;{" "}
                <strong>Add to Home screen / Install app</strong>.
              </p>
            </div>
            <div className="rounded-xl bg-white/10 p-3 text-xs">
              <p className="font-bold text-teal-200">iPhone / iPad (Safari)</p>
              <p className="mt-1 flex flex-wrap items-center gap-1 text-slate-200">
                Tap <Share className="inline h-3.5 w-3.5 text-sky-300" /> <strong>Share</strong> &rarr;{" "}
                <PlusSquare className="inline h-3.5 w-3.5 text-emerald-300" /> <strong>Add to Home Screen</strong>.
              </p>
            </div>
          </div>
        </div>

        {/* Phone Permissions Manager */}
        <div className="mt-5">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-teal-700" />
            <h3 className="text-xs font-extrabold uppercase tracking-wide text-slate-500">
              Manage Phone Permissions
            </h3>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            PRANA-AI only requests access on tap—and works offline/with manual upload even if denied.
          </p>

          <div className="mt-3 space-y-2.5">
            {/* Location */}
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50/70 p-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-white text-teal-700 ring-1 ring-slate-200">
                  <MapPin className="h-4 w-4" />
                </div>
                <div>
                  <p className="text-xs font-bold text-slate-900">GPS Location</p>
                  <p className="text-[11px] text-slate-500">Auto-detects your Area &amp; City</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={perms.location} />
                <button
                  type="button"
                  disabled={busyPerm === "location"}
                  onClick={handleEnableLocation}
                  className="rounded-full bg-white px-3 py-1 text-[11px] font-bold text-slate-800 ring-1 ring-slate-200 hover:bg-slate-100"
                >
                  {busyPerm === "location" ? "Checking..." : "Test GPS"}
                </button>
              </div>
            </div>

            {/* Microphone */}
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50/70 p-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-white text-violet-700 ring-1 ring-slate-200">
                  <Mic className="h-4 w-4" />
                </div>
                <div>
                  <p className="text-xs font-bold text-slate-900">Microphone (Voice Ask)</p>
                  <p className="text-[11px] text-slate-500">Speak questions in Ask PRANA-AI</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={perms.microphone} />
                <button
                  type="button"
                  disabled={busyPerm === "microphone"}
                  onClick={handleEnableMic}
                  className="rounded-full bg-white px-3 py-1 text-[11px] font-bold text-slate-800 ring-1 ring-slate-200 hover:bg-slate-100"
                >
                  {busyPerm === "microphone" ? "Checking..." : "Allow Mic"}
                </button>
              </div>
            </div>

            {/* Camera */}
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50/70 p-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-white text-sky-700 ring-1 ring-slate-200">
                  <Camera className="h-4 w-4" />
                </div>
                <div>
                  <p className="text-xs font-bold text-slate-900">Camera (Room IAQ Audit)</p>
                  <p className="text-[11px] text-slate-500">Snap windows/kitchen (or upload photo)</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={perms.camera} />
                <button
                  type="button"
                  disabled={busyPerm === "camera"}
                  onClick={handleEnableCamera}
                  className="rounded-full bg-white px-3 py-1 text-[11px] font-bold text-slate-800 ring-1 ring-slate-200 hover:bg-slate-100"
                >
                  {busyPerm === "camera" ? "Checking..." : "Allow Camera"}
                </button>
              </div>
            </div>
          </div>

          {feedback && (
            <p className="mt-3 rounded-xl bg-teal-50 px-3 py-2 text-xs font-medium text-teal-900 ring-1 ring-teal-200">
              {feedback}
            </p>
          )}

          {(perms.location === "denied" || perms.microphone === "denied" || perms.camera === "denied") && (
            <div className="mt-3 rounded-xl bg-amber-50 p-3 text-[11px] text-amber-950 ring-1 ring-amber-200">
              <strong>How to unblock on your phone:</strong>{" "}
              {platform.isIOS
                ? "Open iPhone Settings -> Safari (or Chrome) -> Location / Camera / Microphone -> Allow."
                : "Tap the lock icon in Chrome's address bar -> Permissions -> Reset or Allow Location, Camera, and Microphone."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
