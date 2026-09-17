PUNCTUATIONS = [
    "?",
    ",",
    ".",
    "、",
    ";",
    ":",
    "!",
    "…",
    "？",
    "，",
    "。",
    "、",
    "；",
    "：",
    "！",
    "...",
    # 阿拉伯语常用标点也应作为自然断句点，避免脚本文本和 edge-tts
    # 返回的字幕停顿边界不一致，导致后续逐行匹配失败。
    "،",
    "؛",
    "؟",
]

TASK_STATE_FAILED = -1
TASK_STATE_PENDING = 0
TASK_STATE_COMPLETE = 1
TASK_STATE_CANCELLED = 2
TASK_STATE_PROCESSING = 4

CROSS_POST_STATE_PENDING = "pending"
CROSS_POST_STATE_PROCESSING = "processing"
CROSS_POST_STATE_PARTIAL = "partial"
CROSS_POST_STATE_COMPLETE = "complete"
CROSS_POST_STATE_FAILED = "failed"

FILE_TYPE_VIDEOS = ["mp4", "mov", "mkv", "webm"]
FILE_TYPE_IMAGES = ["jpg", "jpeg", "png", "bmp"]

# Monetization Presets
PRESET_CROSS_PLATFORM = "cross_platform"
PRESET_TIKTOK_REWARDS = "tiktok_rewards"
PRESET_YOUTUBE_ORIGINAL = "youtube_shorts_original"
DEFAULT_MONETIZATION_PRESET = PRESET_CROSS_PLATFORM

MONETIZATION_PRESET_CHOICES = [
    PRESET_CROSS_PLATFORM,
    PRESET_TIKTOK_REWARDS,
    PRESET_YOUTUBE_ORIGINAL,
]

# Narrative Structures
STRUCTURE_MYSTERY = "investigative_mystery"
STRUCTURE_EXPLAINER = "explainer"
STRUCTURE_FACT_CONTEXT = "fact_context"
STRUCTURE_MYTH_REALITY = "myth_vs_reality"
STRUCTURE_SHORT_STORY = "short_story"

NARRATIVE_STRUCTURES = [
    STRUCTURE_MYSTERY,
    STRUCTURE_EXPLAINER,
    STRUCTURE_FACT_CONTEXT,
    STRUCTURE_MYTH_REALITY,
    STRUCTURE_SHORT_STORY,
]

# Safety Gate V1 Statuses
SAFETY_STATUS_PASS = "PASS"
SAFETY_STATUS_REVIEW = "REVIEW"
SAFETY_STATUS_BLOCK = "BLOCK"

# Growth Modes (V3.1 Account Warm-Up / Ramp-Up Control)
GROWTH_MODE_WARMUP = "warmup"
GROWTH_MODE_CONSERVATIVE = "conservative"
GROWTH_MODE_NORMAL = "normal"
GROWTH_MODE_SCALE = "scale"
DEFAULT_GROWTH_MODE = GROWTH_MODE_WARMUP

GROWTH_MODES = [
    GROWTH_MODE_WARMUP,
    GROWTH_MODE_CONSERVATIVE,
    GROWTH_MODE_NORMAL,
    GROWTH_MODE_SCALE,
]

GROWTH_MODE_LIMITS = {
    GROWTH_MODE_WARMUP: {
        "youtube": 1,
        "tiktok": 1,
        "min_interval_hours": 8,
    },
    GROWTH_MODE_CONSERVATIVE: {
        "youtube": 2,
        "tiktok": 2,
        "min_interval_hours": 6,
    },
    GROWTH_MODE_NORMAL: {
        "youtube": 3,
        "tiktok": 3,
        "min_interval_hours": 4,
    },
    GROWTH_MODE_SCALE: {
        "youtube": None,
        "tiktok": None,
        "min_interval_hours": 0,
    },
}
