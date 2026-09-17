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
