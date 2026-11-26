import { CalendarClock, Home, MessageSquare, Sliders } from "lucide-react";

export const HOUSEHOLD_STORAGE_KEY = "prana_ai_household_v1";

export const FALLBACK_CITIES = {
  mumbai: {
    name: "Mumbai",
    lat: 19.076,
    lon: 72.8777,
    local_language: "mr",
    areas: [
      { name: "Andheri", lat: 19.1136, lon: 72.8697 },
      { name: "Malad West", lat: 19.1874, lon: 72.8484 },
      { name: "Bandra", lat: 19.0596, lon: 72.8295 },
      { name: "Dadar", lat: 19.0178, lon: 72.8478 },
      { name: "Navi Mumbai", lat: 19.033, lon: 73.0297 }
    ]
  },
  pune: {
    name: "Pune",
    lat: 18.5204,
    lon: 73.8567,
    local_language: "mr",
    areas: [
      { name: "Kothrud", lat: 18.5074, lon: 73.8077 },
      { name: "Hinjewadi", lat: 18.5913, lon: 73.7389 },
      { name: "Shivajinagar", lat: 18.5308, lon: 73.8475 },
      { name: "Baner", lat: 18.559, lon: 73.7868 },
      { name: "Hadapsar", lat: 18.5089, lon: 73.9259 }
    ]
  },
  delhi: {
    name: "Delhi",
    lat: 28.6139,
    lon: 77.209,
    local_language: "hi",
    areas: [
      { name: "Dwarka", lat: 28.5921, lon: 77.046 },
      { name: "Anand Vihar", lat: 28.6469, lon: 77.3164 },
      { name: "Rohini", lat: 28.7495, lon: 77.0565 },
      { name: "Saket", lat: 28.5246, lon: 77.2066 },
      { name: "Connaught Place", lat: 28.6315, lon: 77.2167 }
    ]
  },
  bengaluru: {
    name: "Bangalore",
    lat: 12.9716,
    lon: 77.5946,
    local_language: "kn",
    areas: [
      { name: "Koramangala", lat: 12.9352, lon: 77.6245 },
      { name: "Whitefield", lat: 12.9698, lon: 77.75 },
      { name: "Indiranagar", lat: 12.9784, lon: 77.6408 },
      { name: "Hebbal", lat: 13.0354, lon: 77.5988 }
    ]
  },
  kolkata: {
    name: "Kolkata",
    lat: 22.5726,
    lon: 88.3639,
    local_language: "bn",
    areas: [
      { name: "Salt Lake", lat: 22.5867, lon: 88.4171 },
      { name: "Park Street", lat: 22.5529, lon: 88.3532 },
      { name: "Ballygunge", lat: 22.528, lon: 88.3659 },
      { name: "Howrah", lat: 22.5958, lon: 88.2636 }
    ]
  }
};

export const QUICK_CITIES = [
  { key: "mumbai", label: "Mumbai" },
  { key: "pune", label: "Pune" },
  { key: "delhi", label: "Delhi" },
  { key: "bengaluru", label: "Bangalore" }
];

export const LANGUAGES = [
  { key: "en", label: "English", htmlLang: "en" },
  { key: "hinglish", label: "Hinglish", htmlLang: "en-IN" },
  { key: "hi", label: "Hindi (हिन्दी)", htmlLang: "hi" },
  { key: "mr", label: "Marathi (मराठी)", htmlLang: "mr" },
  { key: "kn", label: "Kannada (ಕನ್ನಡ)", htmlLang: "kn" },
  { key: "bn", label: "Bengali (বাংলা)", htmlLang: "bn" },
  { key: "ta", label: "Tamil (தமிழ்)", htmlLang: "ta" },
  { key: "te", label: "Telugu (తెలుగు)", htmlLang: "te" }
];

export function getHtmlLang(langCode) {
  return LANGUAGES.find((l) => l.key === langCode)?.htmlLang || "en";
}

export const TRANSPORT_MODES = [
  { key: "car_petrol_solo", label: "Petrol Car (Solo)" },
  { key: "car_diesel_solo", label: "Diesel Car (Solo)" },
  { key: "carpool_3p", label: "Carpool (3 People)" },
  { key: "two_wheeler_petrol", label: "2-Wheeler (Petrol)" },
  { key: "auto_cng", label: "CNG Auto-Rickshaw" },
  { key: "city_bus", label: "City Bus" },
  { key: "electric_metro", label: "Electric Metro" },
  { key: "walk_or_cycle", label: "Walk / Cycle" }
];

export const CATEGORY_LABELS = {
  students_kids: "Students & Kids",
  adults_commuters: "Adults & Commuters",
  seniors: "Seniors",
  delivery_riders: "Delivery Riders"
};

export const PRESET_TO_CATEGORY = {
  delhi_family: "adults_commuters",
  mumbai_student: "students_kids",
  pune_elderly: "seniors",
  delivery_rider: "delivery_riders"
};

export const CATEGORY_TEMPLATES = {
  students_kids: {
    user_category: "students_kids",
    budget_tier: "rs_0",
    commute_mode: "auto_cng",
    target_commute_mode: "electric_metro",
    commute_km: 12.0,
    uses_agarbatti_or_coils: false,
    dry_sweeps: true,
    members: [
      { name: "Student", age: 18, conditions: ["adult"] },
      { name: "School Child", age: 9, conditions: ["child"] }
    ],
    rooms: [
      { name: "Road-Side Living / Study Room", ext_windows: 2, road_facing: true, kitchen_adjacent: false, large_volume: false },
      { name: "Inner Bedroom", ext_windows: 1, road_facing: false, kitchen_adjacent: false, large_volume: false }
    ],
    activities: [
      { id: "campus_commute", name: "School / College Commute (12 km)", flexibility: "fixed", planned_hour: 8, duration_min: 45, activity_level: "seated", member_name: "Student", current_mask: "none", is_commute: true, is_work_shift: false },
      { id: "sports_play", name: "Outdoor Sports / Park Play", flexibility: "flexible", planned_hour: 17, duration_min: 45, activity_level: "child_play", member_name: "School Child", current_mask: "none", is_commute: false, is_work_shift: false },
      { id: "evening_jog", name: "Campus Run / Walk", flexibility: "flexible", planned_hour: 19, duration_min: 35, activity_level: "running_or_outdoor_work", member_name: "Student", current_mask: "none", is_commute: false, is_work_shift: false }
    ]
  },
  adults_commuters: {
    user_category: "adults_commuters",
    budget_tier: "under_2200",
    commute_mode: "car_petrol_solo",
    target_commute_mode: "electric_metro",
    commute_km: 16.0,
    uses_agarbatti_or_coils: false,
    dry_sweeps: true,
    members: [{ name: "Commuter", age: 34, conditions: ["adult"] }],
    rooms: [
      { name: "Front Living Room", ext_windows: 2, road_facing: true, kitchen_adjacent: true, large_volume: true },
      { name: "Inner Bedroom", ext_windows: 1, road_facing: false, kitchen_adjacent: false, large_volume: false }
    ],
    activities: [
      { id: "office_commute", name: "Office Commute (16 km)", flexibility: "fixed", planned_hour: 9, duration_min: 60, activity_level: "seated", member_name: "Commuter", current_mask: "none", is_commute: true, is_work_shift: false },
      { id: "brisk_walk", name: "Daily Brisk Walk", flexibility: "flexible", planned_hour: 7, duration_min: 40, activity_level: "brisk_walk", member_name: "Commuter", current_mask: "none", is_commute: false, is_work_shift: false },
      { id: "errand_walk", name: "Evening Grocery Trip", flexibility: "flexible", planned_hour: 19, duration_min: 30, activity_level: "light_walk", member_name: "Commuter", current_mask: "none", is_commute: false, is_work_shift: false }
    ]
  },
  seniors: {
    user_category: "seniors",
    budget_tier: "under_500",
    commute_mode: "auto_cng",
    target_commute_mode: "city_bus",
    commute_km: 6.0,
    uses_agarbatti_or_coils: true,
    dry_sweeps: true,
    members: [{ name: "Senior Member", age: 70, conditions: ["elderly", "copd"] }],
    rooms: [
      { name: "Front Veranda", ext_windows: 2, road_facing: true, kitchen_adjacent: false, large_volume: true },
      { name: "Inner Quiet Bedroom", ext_windows: 1, road_facing: false, kitchen_adjacent: false, large_volume: false }
    ],
    activities: [
      { id: "clinic_visit", name: "Clinic / Pharmacy Visit (6 km)", flexibility: "fixed", planned_hour: 10, duration_min: 40, activity_level: "seated", member_name: "Senior Member", current_mask: "none", is_commute: true, is_work_shift: false },
      { id: "senior_walk", name: "Morning Park Walk", flexibility: "flexible", planned_hour: 6, duration_min: 45, activity_level: "elderly_walk", member_name: "Senior Member", current_mask: "cloth", is_commute: false, is_work_shift: false },
      { id: "market_walk", name: "Vegetable Market Errand", flexibility: "flexible", planned_hour: 8, duration_min: 30, activity_level: "light_walk", member_name: "Senior Member", current_mask: "none", is_commute: false, is_work_shift: false }
    ]
  },
  delivery_riders: {
    user_category: "delivery_riders",
    budget_tier: "under_500",
    commute_mode: "two_wheeler_petrol",
    target_commute_mode: "two_wheeler_petrol",
    commute_km: 40.0,
    uses_agarbatti_or_coils: true,
    dry_sweeps: true,
    members: [{ name: "Delivery Rider", age: 29, conditions: ["outdoor_worker"] }],
    rooms: [
      { name: "Road-Side Room Entry", ext_windows: 1, road_facing: true, kitchen_adjacent: true, large_volume: false },
      { name: "Inner Sleeping Corner", ext_windows: 0, road_facing: false, kitchen_adjacent: false, large_volume: false }
    ],
    activities: [
      { id: "shift_morning", name: "Morning-Afternoon Delivery Shift (4h)", flexibility: "fixed", planned_hour: 8, duration_min: 240, activity_level: "running_or_outdoor_work", member_name: "Delivery Rider", current_mask: "cloth", is_commute: true, is_work_shift: true },
      { id: "shift_evening", name: "Evening Peak Delivery Shift (4h)", flexibility: "fixed", planned_hour: 17, duration_min: 240, activity_level: "running_or_outdoor_work", member_name: "Delivery Rider", current_mask: "cloth", is_commute: true, is_work_shift: true },
      { id: "lunch_rest", name: "Midday Tea / Stretch Break", flexibility: "flexible", planned_hour: 13, duration_min: 30, activity_level: "light_walk", member_name: "Delivery Rider", current_mask: "none", is_commute: false, is_work_shift: false }
    ]
  }
};

export const TABS = [
  { id: "plan", label: "Today's Plan", shortLabel: "Today", Icon: CalendarClock },
  { id: "indoor", label: "Home & Indoor", shortLabel: "Home", Icon: Home },
  { id: "impact", label: "Impact & What-If", shortLabel: "What-If", Icon: Sliders },
  { id: "chat", label: "Ask AI", shortLabel: "Ask AI", Icon: MessageSquare }
];
