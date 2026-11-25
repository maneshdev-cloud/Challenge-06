export const SPEECH_LANG_MAP = {
  en: "en-IN",
  hinglish: "en-IN",
  hi: "hi-IN",
  mr: "mr-IN",
  kn: "kn-IN",
  bn: "bn-IN",
  ta: "ta-IN",
  te: "te-IN"
};

export function detectPlatform() {
  if (typeof window === "undefined" || typeof navigator === "undefined") {
    return { isIOS: false, isAndroid: false, isMobile: false, isStandalone: false };
  }
  const ua = navigator.userAgent || "";
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
  const isMobile = isIOS || isAndroid;
  const isStandalone =
    window.matchMedia?.("(display-mode: standalone)").matches || Boolean(window.navigator.standalone);
  return { isIOS, isAndroid, isMobile, isStandalone };
}

export function canUseSpeechSynthesis() {
  return typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";
}

export function getSpeechRecognitionCtor() {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export function formatTextForSpeech(text) {
  if (!text) return "";
  return text
    .replace(/\*\*/g, "")
    .replace(/µg\/m3|ug\/m3/gi, " micrograms per cubic meter ")
    .replace(/\bCO2e\b|\bCO2\b/gi, " C O 2 ")
    .replace(/\bNAQI\b/gi, " N A Q I ")
    .replace(/\bAQI\b/gi, " A Q I ")
    .replace(/\bPM2\.5\b/gi, " P M 2.5 ")
    .replace(/^\s*[-*]\s+/gm, "")
    .replace(/\n+/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
}

export function pickBestVoice(langKey) {
  if (!canUseSpeechSynthesis()) return { voice: null, langTag: SPEECH_LANG_MAP[langKey] || "en-IN" };
  const target = SPEECH_LANG_MAP[langKey] || "en-IN";
  const prefix = target.split("-")[0].toLowerCase();
  const voices = window.speechSynthesis.getVoices() || [];

  const exact = voices.find((v) => v.lang?.toLowerCase() === target.toLowerCase());
  if (exact) return { voice: exact, langTag: exact.lang };

  const prefixMatch = voices.find((v) => v.lang?.toLowerCase().startsWith(`${prefix}-`) || v.lang?.toLowerCase() === prefix);
  if (prefixMatch) return { voice: prefixMatch, langTag: prefixMatch.lang };

  const enIn = voices.find((v) => v.lang?.toLowerCase() === "en-in");
  if (enIn) return { voice: enIn, langTag: enIn.lang };

  const anyEn = voices.find((v) => v.lang?.toLowerCase().startsWith("en"));
  return { voice: anyEn || voices[0] || null, langTag: target };
}

export function isSecureOriginForDevices() {
  if (typeof window === "undefined") return true;
  if (window.isSecureContext) return true;
  return window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
}

export async function queryPermissionState(name) {
  if (typeof navigator === "undefined") return "unsupported";
  if (!isSecureOriginForDevices()) return "insecure_context";

  if (name === "geolocation" && !("geolocation" in navigator)) return "unsupported";
  if ((name === "microphone" || name === "camera") && !navigator.mediaDevices?.getUserMedia) {
    return "unsupported";
  }

  if (navigator.permissions?.query) {
    try {
      const res = await navigator.permissions.query({ name });
      return res.state; // "granted" | "prompt" | "denied"
    } catch {
      // Safari / iOS throws TypeError for camera/microphone in Permissions API
      return "prompt";
    }
  }
  return "prompt";
}

export async function testAllPhonePermissions() {
  const [location, microphone, camera] = await Promise.all([
    queryPermissionState("geolocation"),
    queryPermissionState("microphone"),
    queryPermissionState("camera")
  ]);
  return { location, microphone, camera };
}

export async function requestMicrophoneAccess() {
  if (!isSecureOriginForDevices()) {
    return { state: "insecure_context", message: "Microphone requires HTTPS on mobile browsers." };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return { state: "unsupported", message: "Microphone access is not supported in this browser." };
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    return { state: "granted", message: "Microphone access enabled for Voice Ask." };
  } catch (err) {
    const denied = err?.name === "NotAllowedError" || err?.name === "PermissionDeniedError";
    return {
      state: denied ? "denied" : "error",
      message: denied
        ? "Microphone blocked. Enable Microphone in iOS Safari Settings or Android Site Settings."
        : `Could not open microphone (${err?.message || "hardware unavailable"}).`
    };
  }
}

export async function requestCameraAccess() {
  if (!isSecureOriginForDevices()) {
    return { state: "insecure_context", message: "Live camera requires HTTPS on mobile browsers (Upload Photo still works)." };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return { state: "unsupported", message: "Direct camera API unsupported; you can still upload from your gallery." };
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    stream.getTracks().forEach((t) => t.stop());
    return { state: "granted", message: "Camera ready for Room IAQ photo inspection." };
  } catch (err) {
    const denied = err?.name === "NotAllowedError" || err?.name === "PermissionDeniedError";
    return {
      state: denied ? "denied" : "error",
      message: denied
        ? "Camera blocked on this phone. Allow Camera in browser settings, or pick a saved photo from Gallery."
        : `Could not start camera (${err?.message || "use gallery picker instead"}).`
    };
  }
}
