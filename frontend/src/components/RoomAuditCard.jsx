import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Camera,
  CheckCircle2,
  ImagePlus,
  Loader2,
  Sparkles,
  Upload
} from "lucide-react";
import { auditRoomPhoto } from "../api/client";
import { getHtmlLang } from "../data/constants";

const ALLOWED_TYPES = new Set(["image/jpeg", "image/jpg", "image/png", "image/webp"]);
const MAX_BYTES = 5 * 1024 * 1024;

async function compressImageIfNeeded(file) {
  if (file.size <= 900 * 1024) return file;

  return new Promise((resolve) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      try {
        const maxSide = 1280;
        let { width, height } = img;
        if (width > maxSide || height > maxSide) {
          const scale = maxSide / Math.max(width, height);
          width = Math.round(width * scale);
          height = Math.round(height * scale);
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, width, height);
        canvas.toBlob(
          (blob) => {
            URL.revokeObjectURL(url);
            if (!blob) {
              resolve(file);
              return;
            }
            const compressed = new File(
              [blob],
              (file.name || "room").replace(/\.\w+$/, ".jpg"),
              { type: "image/jpeg" }
            );
            resolve(compressed.size < file.size ? compressed : file);
          },
          "image/jpeg",
          0.82
        );
      } catch {
        URL.revokeObjectURL(url);
        resolve(file);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(file);
    };
    img.src = url;
  });
}

export default function RoomAuditCard({
  city,
  areaName,
  language,
  currentNaqi,
  onOpenPermissions
}) {
  const cameraInputRef = useRef(null);
  const galleryInputRef = useRef(null);

  const [previewUrl, setPreviewUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [result, setResult] = useState(null);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  async function handleFileSelected(e) {
    const rawFile = e.target.files?.[0];
    e.target.value = "";
    if (!rawFile) return;

    setErrorMsg(null);
    const typeLower = (rawFile.type || "").toLowerCase();
    if (typeLower && !ALLOWED_TYPES.has(typeLower) && !typeLower.startsWith("image/")) {
      setErrorMsg("Please choose a JPG, PNG, or WebP photo of your room or kitchen.");
      return;
    }

    const optimized = await compressImageIfNeeded(rawFile);
    if (optimized.size > MAX_BYTES) {
      setErrorMsg("Photo exceeds 5 MB even after compression. Try a smaller photo.");
      return;
    }

    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(optimized));
    setResult(null);
    setLoading(true);

    try {
      const data = await auditRoomPhoto(optimized, {
        city,
        area_name: areaName,
        language,
        current_naqi: currentNaqi
      });
      setResult(data);
    } catch (err) {
      setErrorMsg(err.message || "Could not analyze photo right now.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-3xl bg-white p-5 shadow-md shadow-slate-200/60 ring-1 ring-slate-200/70 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-50 text-sky-700 ring-1 ring-sky-200/70">
            <Camera className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-base font-extrabold text-slate-900">Audit My Room Photo</h3>
            <p className="mt-0.5 text-xs text-slate-600">
              Snap a window, balcony door, or kitchen photo for 3 practical ₹0–₹500 sealing fixes.
            </p>
          </div>
        </div>

        {result && (
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold ${result.source === "gemini"
              ? "bg-violet-50 text-violet-900 ring-1 ring-violet-200"
              : "bg-slate-100 text-slate-700"
              }`}
          >
            <Sparkles className="h-3 w-3" aria-hidden="true" />
            <span>
              {result.source === "gemini" ? "Gemini Vision" : "Deterministic Fallback Engine"}
            </span>
          </span>
        )}
      </div>

      {/* Accessible Hidden File Inputs */}
      <input
        ref={cameraInputRef}
        type="file"
        aria-label="Capture room or kitchen photo with camera"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        onChange={handleFileSelected}
        className="hidden"
      />
      <input
        ref={galleryInputRef}
        type="file"
        aria-label="Upload room or kitchen photo from device"
        accept="image/jpeg,image/png,image/webp"
        onChange={handleFileSelected}
        className="hidden"
      />

      <div className="mt-4 flex flex-wrap items-center gap-2.5">
        <button
          type="button"
          disabled={loading}
          onClick={() => cameraInputRef.current?.click()}
          className="inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-4 py-2 text-xs font-bold text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-50"
        >
          <Camera className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Snap Room / Kitchen</span>
        </button>

        <button
          type="button"
          disabled={loading}
          onClick={() => galleryInputRef.current?.click()}
          className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-4 py-2 text-xs font-bold text-slate-800 ring-1 ring-slate-200 transition hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-50"
        >
          <Upload className="h-3.5 w-3.5 text-slate-600" aria-hidden="true" />
          <span>Upload Photo (JPG/PNG/WebP)</span>
        </button>

        {onOpenPermissions && (
          <button
            type="button"
            onClick={onOpenPermissions}
            className="text-xs font-semibold text-teal-800 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            Camera permission help?
          </button>
        )}
      </div>

      {errorMsg && (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-2xl bg-rose-50 px-3.5 py-2.5 text-xs font-medium text-rose-900 ring-1 ring-rose-200"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-700" aria-hidden="true" />
          <span>{errorMsg}</span>
        </div>
      )}

      {(previewUrl || loading || result) && (
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-[160px_1fr]">
          {previewUrl ? (
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-100">
              <img
                src={previewUrl}
                alt="Uploaded room preview"
                className="h-40 w-full object-cover sm:h-full"
              />
            </div>
          ) : (
            <div className="flex h-36 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 text-slate-500">
              <ImagePlus className="h-6 w-6" aria-hidden="true" />
            </div>
          )}

          <div className="space-y-3">
            {loading && (
              <div
                role="status"
                aria-live="polite"
                className="flex h-full min-h-[120px] flex-col items-center justify-center gap-2 rounded-2xl bg-slate-50 p-4 text-center ring-1 ring-slate-200/70"
              >
                <Loader2 className="h-5 w-5 animate-spin text-teal-700" aria-hidden="true" />
                <p className="text-xs font-bold text-slate-700">Inspecting room ventilation...</p>
                <p className="text-[11px] text-slate-600">
                  Checking window seals, exhaust flow &amp; dust traps
                </p>
              </div>
            )}

            {result && !loading && (
              <div aria-live="polite" lang={getHtmlLang(language)} className="space-y-3">
                <p className="rounded-2xl bg-slate-50 px-3.5 py-2.5 text-xs font-medium leading-relaxed text-slate-700 ring-1 ring-slate-200/70">
                  {result.room_summary}
                </p>

                <div className="space-y-2">
                  {result.tips.map((tip, idx) => (
                    <div
                      key={idx}
                      className="rounded-2xl bg-gradient-to-br from-emerald-50/50 to-white p-3 ring-1 ring-slate-200/80"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1.5 text-xs font-bold text-slate-900">
                          <CheckCircle2
                            className="h-3.5 w-3.5 shrink-0 text-teal-700"
                            aria-hidden="true"
                          />
                          {tip.title}
                        </span>
                        <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-900">
                          {tip.cost_inr}
                        </span>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-slate-700">{tip.action}</p>
                      <p className="mt-1 text-[11px] font-semibold text-teal-800">
                        {tip.why_it_helps}
                      </p>
                    </div>
                  ))}
                </div>

                <p className="text-[11px] text-slate-600">{result.disclaimer}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
