import warnings
from enum import Enum
from typing import Any, List, Literal, Optional, Union

import pydantic
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import config
from app.models import const

# 忽略 Pydantic 的特定警告
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message="Field name.*shadows an attribute in parent.*",
)


class VideoConcatMode(str, Enum):
    random = "random"
    sequential = "sequential"


class VideoTransitionMode(str, Enum):
    none = None
    shuffle = "Shuffle"
    fade_in = "FadeIn"
    fade_out = "FadeOut"
    slide_in = "SlideIn"
    slide_out = "SlideOut"
    zoom_in = "ZoomIn"
    zoom_out = "ZoomOut"


class VideoAspect(str, Enum):
    landscape = "16:9"
    portrait = "9:16"
    square = "1:1"

    def to_resolution(self):
        if self == VideoAspect.landscape:
            return 1920, 1080
        elif self == VideoAspect.portrait:
            return 1080, 1920
        elif self == VideoAspect.square:
            return 1080, 1080
        raise ValueError(f"unsupported video aspect: {self}")


class VideoFitMode(str, Enum):
    """How source clips with a different aspect ratio fill the output canvas."""

    cover = "cover"
    contain = "contain"


SubtitleDisplayMode = Literal["sentence", "word_by_word"]
SubtitleAnimation = Literal["none", "pop_spring"]
_SUBTITLE_DISPLAY_MODES = ("sentence", "word_by_word")
_SUBTITLE_ANIMATIONS = ("none", "pop_spring")


def _get_valid_ui_choice(key: str, allowed_values: tuple[str, ...], default: str) -> str:
    """
    读取经过校验的 WebUI 枚举配置，兼容旧用户可能残留的无效值。

    请求体由 Pydantic 的 Literal 严格校验，拼写错误会返回明确的字段校验错误；
    配置文件则需要宽容处理，避免用户升级后因为历史手工配置错误导致整个服务
    无法启动。HTTP 状态码由应用统一的校验异常处理器决定，这里不绑定具体数值。
    """
    configured_value = config.ui.get(key, default)
    return configured_value if configured_value in allowed_values else default


_Config = ConfigDict(
    arbitrary_types_allowed=True,
    # Note: ensure your key names match renamed V2 parameters if needed
)


@pydantic.dataclasses.dataclass(config=_Config)
class MaterialInfo:
    provider: str = "pexels"
    url: str = ""
    duration: int = 0
    # 在线素材搜索会附带经过筛选的公开来源信息，供搜索缓存和任务记录复用。
    # 本地上传素材不需要填写；写入任务文件前仍会按字段白名单重新构造，
    # 避免外部请求传入的签名 URL、凭据或无关字段进入持久化数据。
    source_info: Optional[dict[str, Any]] = None


class VideoParams(BaseModel):
    """
    {
      "video_subject": "",
      "video_aspect": "横屏 16:9（西瓜视频）",
      "voice_name": "女生-晓晓",
      "bgm_name": "random",
      "font_name": "STHeitiMedium 黑体-中",
      "text_color": "#FFFFFF",
      "font_size": 60,
      "stroke_color": "#000000",
      "stroke_width": 1.5
    }
    """

    video_subject: str
    video_script: str = ""  # Script used to generate the video
    video_terms: Optional[str | list] = None  # Keywords used to generate the video
    video_aspect: Optional[VideoAspect] = VideoAspect.portrait.value
    video_fit_mode: VideoFitMode = VideoFitMode.cover
    video_concat_mode: Optional[VideoConcatMode] = VideoConcatMode.random.value
    video_transition_mode: Optional[VideoTransitionMode] = None
    video_clip_duration: int = Field(default=5, ge=1)
    video_clip_speed: Optional[float] = 1.0
    match_materials_to_script: bool = False
    video_count: int = Field(default=1, ge=1)

    video_source: Optional[str] = "pexels"
    video_materials: Optional[List[MaterialInfo]] = (
        None  # Materials used to generate the video
    )

    custom_audio_file: Optional[str] = (
        None  # Custom audio file path, will ignore TTS and can still use Whisper subtitles
    )
    video_language: Optional[str] = ""  # auto detect

    voice_name: Optional[str] = ""
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.0
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2
    bgm_default_mood: str = "neutral"
    # 视频配乐供应商共用提示词，WebUI 新任务统一写入该字段。保留下面的
    # Sonilo 专用字段以兼容旧任务记录和现有 CLI 参数。
    video_music_prompt: str = Field(default="", max_length=2000)
    sonilo_bgm_prompt: str = Field(default="", max_length=2000)

    subtitle_enabled: Optional[bool] = True
    subtitle_required: bool = False
    final_media_quality_required: bool = False
    scene_based_generation_enabled: bool = False
    visual_generation_enabled: bool = False
    generated_image_enabled: bool = False
    generated_video_enabled: bool = False
    stock_high_confidence_threshold: float = 60.0
    generated_image_threshold: float = 35.0
    preferred_video_provider: Optional[str] = "disabled"
    preferred_image_provider: Optional[str] = "nano_banana"
    image_to_video_provider: Optional[str] = "disabled"
    still_motion_enabled: bool = True
    comfyui_endpoint: Optional[str] = "http://127.0.0.1:8188"
    thematic_sources_enabled: bool = True
    thematic_score_threshold: float = 40.0
    adaptive_learning_enabled: bool = True
    subtitle_position: Optional[str] = config.ui.get(
        "subtitle_position", "bottom"
    )  # top, bottom, center, custom, two_thirds_bottom
    subtitle_display_mode: SubtitleDisplayMode = _get_valid_ui_choice(
        "subtitle_display_mode", _SUBTITLE_DISPLAY_MODES, "sentence"
    )
    subtitle_animation: SubtitleAnimation = _get_valid_ui_choice(
        "subtitle_animation", _SUBTITLE_ANIMATIONS, "none"
    )
    custom_position: float = config.ui.get("custom_position", 70.0)
    font_name: Optional[str] = "STHeitiMedium.ttc"
    text_fore_color: Optional[str] = "#FFFFFF"
    text_background_color: Union[bool, str] = False
    rounded_subtitle_background: bool = False

    font_size: int = 60
    stroke_color: Optional[str] = "#000000"
    stroke_width: float = 2.0
    n_threads: Optional[int] = 2
    paragraph_number: int = Field(default=1, ge=1, le=10)
    video_script_prompt: str = Field(default="", max_length=2000)
    custom_system_prompt: str = Field(default="", max_length=8000)
    monetization_preset: Optional[str] = const.DEFAULT_MONETIZATION_PRESET
    narrative_structure: Optional[str] = None
    safety_status: Optional[str] = None
    safety_reasons: Optional[str] = None
    profile_id: Optional[str] = None
    niche: Optional[str] = None
    region: Optional[str] = None
    topic_brief: Optional[str] = None
    # Channel Factory / Flow Integration (Fase V1.5E-E)
    visual_director_enabled: bool = False
    visual_style_brief: str = ""
    flow_enabled: bool = False
    flow_scene_count: int = 6
    stock_fallback_enabled: bool = True

    # Virtual Presenter / Character Overlay (Fase V14-C)
    avatar_mode: str = Field(default=const.DEFAULT_AVATAR_MODE)
    avatar_provider: str = Field(default="local")
    avatar_character_id: str = Field(default="")
    avatar_asset_path: str = Field(default="")
    avatar_position: str = Field(default=const.DEFAULT_AVATAR_POSITION)
    avatar_scale: float = Field(default=0.38, ge=0.1, le=1.0)
    avatar_opacity: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("avatar_mode", mode="before")
    @classmethod
    def validate_avatar_mode(cls, v: Any) -> str:
        clean = str(v or const.DEFAULT_AVATAR_MODE).lower().strip()
        if clean not in const.AVATAR_MODES:
            return const.DEFAULT_AVATAR_MODE
        return clean

    @field_validator("avatar_position", mode="before")
    @classmethod
    def validate_avatar_position(cls, v: Any) -> str:
        clean = str(v or const.DEFAULT_AVATAR_POSITION).lower().strip()
        if clean not in const.AVATAR_POSITIONS:
            return const.DEFAULT_AVATAR_POSITION
        return clean

    @field_validator("avatar_scale", mode="before")
    @classmethod
    def validate_avatar_scale(cls, v: Any) -> float:
        try:
            val = float(v)
            return max(0.1, min(1.0, val))
        except (ValueError, TypeError):
            return 0.38

    @field_validator("avatar_opacity", mode="before")
    @classmethod
    def validate_avatar_opacity(cls, v: Any) -> float:
        try:
            val = float(v)
            return max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            return 1.0



class SubtitleRequest(BaseModel):
    video_script: str
    video_language: Optional[str] = ""
    voice_name: Optional[str] = "zh-CN-XiaoxiaoNeural-Female"
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.2
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2
    subtitle_position: Optional[str] = config.ui.get("subtitle_position", "bottom")
    subtitle_display_mode: SubtitleDisplayMode = _get_valid_ui_choice(
        "subtitle_display_mode", _SUBTITLE_DISPLAY_MODES, "sentence"
    )
    subtitle_animation: SubtitleAnimation = _get_valid_ui_choice(
        "subtitle_animation", _SUBTITLE_ANIMATIONS, "none"
    )
    font_name: Optional[str] = "STHeitiMedium.ttc"
    text_fore_color: Optional[str] = "#FFFFFF"
    text_background_color: Union[bool, str] = False
    rounded_subtitle_background: bool = False
    font_size: int = 60
    stroke_color: Optional[str] = "#000000"
    stroke_width: float = 2.0
    video_source: Optional[str] = "local"
    subtitle_enabled: Optional[str] = "true"


class AudioRequest(BaseModel):
    video_script: str
    video_language: Optional[str] = ""
    voice_name: Optional[str] = "zh-CN-XiaoxiaoNeural-Female"
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.2
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2
    video_source: Optional[str] = "local"


class VideoScriptParams:
    """
    {
      "video_subject": "春天的花海",
      "video_language": "",
      "paragraph_number": 1,
      "video_script_prompt": "",
      "custom_system_prompt": ""
    }
    """

    video_subject: Optional[str] = "春天的花海"
    video_language: Optional[str] = ""
    paragraph_number: int = Field(default=1, ge=1, le=10)
    video_script_prompt: str = Field(default="", max_length=2000)
    custom_system_prompt: str = Field(default="", max_length=8000)


class VideoTermsParams:
    """
    {
      "video_subject": "",
      "video_script": "",
      "amount": 5,
      "match_materials_to_script": false
    }
    """

    video_subject: Optional[str] = "春天的花海"
    video_script: Optional[str] = (
        "春天的花海，如诗如画般展现在眼前。万物复苏的季节里，大地披上了一袭绚丽多彩的盛装。金黄的迎春、粉嫩的樱花、洁白的梨花、艳丽的郁金香……"
    )
    amount: Optional[int] = 5
    match_materials_to_script: bool = False


class VideoSocialMetadataParams:
    """
    {
      "video_subject": "A day in Shanghai",
      "video_script": "",
      "language": "auto",
      "platform": "tiktok"
    }
    """

    video_subject: Optional[str] = Field(default="A day in Shanghai", max_length=500)
    video_script: Optional[str] = Field(default="", max_length=8000)
    language: Optional[str] = Field(default="auto", max_length=64)
    platform: Optional[str] = Field(default="tiktok", max_length=64)


class TaskVideoRequest(VideoParams, BaseModel):
    pass


class TaskQueryRequest(BaseModel):
    pass


class VideoScriptRequest(VideoScriptParams, BaseModel):
    pass


class VideoTermsRequest(VideoTermsParams, BaseModel):
    pass


class VideoSocialMetadataRequest(VideoSocialMetadataParams, BaseModel):
    pass


# ---------------------------
# ----- RESPONSE MODELS -----
# ---------------------------
class BaseResponse(BaseModel):
    status: int = 200
    message: Optional[str] = "success"
    data: Any = None


# ---- DATA MODELS ----
class TaskResponseData(BaseModel):
    task_id: str


class TaskStatusData(BaseModel):
    """任务查询对外保证的稳定字段；历史和扩展字段继续原样透传。"""

    model_config = ConfigDict(extra="allow")

    task_id: str
    state: int
    progress: int = 0
    videos: Optional[List[str]] = None
    combined_videos: Optional[List[str]] = None
    failed_stage: Optional[str] = None
    error: Optional[str] = None
    cross_post_state: Optional[
        Literal["pending", "processing", "complete", "failed"]
    ] = None
    cross_post_results: Optional[List[dict[str, Any]]] = None
    cross_post_error: Optional[str] = None


class TaskListData(BaseModel):
    """分页任务列表结构。"""

    tasks: List[TaskStatusData]
    total: int
    page: int
    page_size: int


class VideoScriptData(BaseModel):
    video_script: str


class VideoTermsData(BaseModel):
    video_terms: List[str]


class VideoSocialMetadataData(BaseModel):
    title: str
    caption: str
    hashtags: List[str]


class FileData(BaseModel):
    name: str
    size: int
    file: str


class BgmRetrieveData(BaseModel):
    files: List[FileData]


class BgmUploadData(BaseModel):
    file: str


class VideoMaterialRetrieveData(BaseModel):
    files: List[FileData]


class VideoMaterialUploadData(BaseModel):
    file: str


# ---- RESPONSE MODELS ----
class TaskResponse(BaseResponse):
    data: TaskResponseData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
                },
            },
        }
    )


class TaskQueryResponse(BaseResponse):
    """
    任务查询会返回生成状态和可选的跨平台发布状态。

    生成失败时包含 `failed_stage` 和 `error`；生成完成后如果启用了自动发布，
    `cross_post_state` 会依次进入 pending、processing、complete 或 failed。
    """

    data: TaskStatusData

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": 200,
                    "message": "success",
                    "data": {
                        "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
                        "state": 1,
                        "progress": 100,
                        "videos": ["/tasks/example/final-1.mp4"],
                        "cross_post_state": "complete",
                        "cross_post_results": [{"success": True}],
                    },
                },
                {
                    "status": 200,
                    "message": "success",
                    "data": {
                        "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
                        "state": -1,
                        "progress": 30,
                        "failed_stage": "audio",
                        "error": "TTS request timed out",
                    },
                },
            ],
        }
    )


class TaskListResponse(BaseResponse):
    """任务列表使用独立响应模型，避免与单任务查询混用文档结构。"""

    data: TaskListData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "tasks": [
                        {
                            "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
                            "state": 4,
                            "progress": 50,
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 10,
                },
            }
        }
    )


class TaskDeletionResponse(BaseResponse):
    data: None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": None,
            },
        }
    )


class VideoScriptResponse(BaseResponse):
    data: VideoScriptData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "video_script": "春天的花海，是大自然的一幅美丽画卷。在这个季节里，大地复苏，万物生长，花朵争相绽放，形成了一片五彩斑斓的花海..."
                },
            },
        }
    )


class VideoTermsResponse(BaseResponse):
    data: VideoTermsData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {"video_terms": ["sky", "tree"]},
            },
        }
    )


class VideoSocialMetadataResponse(BaseResponse):
    data: VideoSocialMetadataData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "title": "A Day in Shanghai You Should Not Miss",
                    "caption": "Save this quick Shanghai inspiration and follow for more short travel ideas.",
                    "hashtags": ["#shorts", "#travel", "#shanghai", "#viral", "#fyp"],
                },
            },
        }
    )


class BgmRetrieveResponse(BaseResponse):
    data: BgmRetrieveData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "files": [
                        {
                            "name": "4fca18fce7344f3aa824777a40d45c8c.mp3",
                            "size": 1891269,
                            "file": "4fca18fce7344f3aa824777a40d45c8c.mp3",
                        }
                    ]
                },
            },
        }
    )


class BgmUploadResponse(BaseResponse):
    data: BgmUploadData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {"file": "4fca18fce7344f3aa824777a40d45c8c.mp3"},
            },
        }
    )


class VideoMaterialRetrieveResponse(BaseResponse):
    data: VideoMaterialRetrieveData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "files": [
                        {
                            "name": "example.mp4",
                            "size": 12345678,
                            "file": "/MoneyPrinterTurbo/resource/videos/example.mp4",
                        }
                    ]
                },
            },
        }
    )


class VideoMaterialUploadResponse(BaseResponse):
    data: VideoMaterialUploadData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "file": "/MoneyPrinterTurbo/resource/videos/example.mp4",
                },
            },
        }
    )


# =============================================================================
# V16.4 — Scene-Based Video Generation Models
# =============================================================================

class ScenePlanItem(BaseModel):
    scene_index: int = Field(..., ge=1, description="1-based scene index in deterministic order")
    narration: str = Field(..., min_length=1, description="Narration text corresponding to this scene")
    search_terms: List[str] = Field(default_factory=list, description="Ordered list of visual search terms for this scene")
    duration_hint: Optional[float] = Field(default=None, description="Estimated duration in seconds for this scene")
    visual_intent: Optional[str] = Field(default=None, description="Visual intent or mood description for this scene")
    visual_intent_v2: Optional[dict] = Field(default=None, description="Structured visual intent (V16.5 Visual Matching v2)")
    source_strategy: Optional[str] = Field(default=None, description="Preferred source or strategy for this scene")


class ScenePlan(BaseModel):
    scenes: List[ScenePlanItem] = Field(default_factory=list, description="Ordered list of scenes in narrative sequence")
    total_scenes: int = Field(default=0, ge=0, description="Total count of scenes in the plan")
    script_hash: Optional[str] = Field(default=None, description="SHA256 or hash of the source script")
    planner_version: str = Field(default="v1.0", description="Planner algorithm version")


class SceneMaterialSelection(BaseModel):
    scene_index: int = Field(..., ge=1, description="Scene index bound to this material")
    material_path: str = Field(..., description="Local path to downloaded or cached video material")
    provider: str = Field(default="pexels", description="Provider source (pexels, pixabay, etc.)")
    asset_id: Optional[str] = Field(default=None, description="Provider asset identifier")
    source_url: Optional[str] = Field(default=None, description="Original source URL or page")
    search_term_used: str = Field(default="", description="Search term that successfully resolved this material")
    fallback_used: bool = Field(default=False, description="Whether fallback logic was used to find this material")
    duration: float = Field(default=0.0, ge=0.0, description="Duration in seconds of the material")
    provenance: Optional[dict] = Field(default=None, description="Asset provenance details for copyright compliance")
    visual_intent: Optional[dict] = Field(default=None, description="Visual intent used for material matching")
    match_score: Optional[float] = Field(default=None, description="Deterministic match score (0-100)")
    selection_reason: Optional[str] = Field(default=None, description="Reason or breakdown of candidate selection")
    queries_tried: Optional[List[str]] = Field(default=None, description="Search queries evaluated for this scene")
    fallback_tier: Optional[int] = Field(default=None, description="Fallback tier index used (0=primary, 1=alt1, etc.)")
    media_type: Optional[str] = Field(default="stock", description="Media type: stock, generated_video, generated_image, image_motion")
    model: Optional[str] = Field(default=None, description="AI Model used if generated")
    generation_time: Optional[float] = Field(default=None, description="Generation time in seconds if AI generated")
    fallback_reason: Optional[str] = Field(default=None, description="Fallback reason if AI generation was bypassed or failed")
    visual_source_type: Optional[str] = Field(default="stock", description="Visual source: stock, generated_image, generated_video, image_motion")
    stock_match_score: Optional[float] = Field(default=None, description="Visual matching v2 candidate score")
    generation_provider: Optional[str] = Field(default=None, description="Provider used if generated")
    generation_model: Optional[str] = Field(default=None, description="Model used if generated")
    generation_prompt: Optional[str] = Field(default=None, description="Synthesized prompt used for generation")
    generation_status: Optional[str] = Field(default=None, description="Status: success, fallback, bypassed")
    generated_asset_path: Optional[str] = Field(default=None, description="Path to generated asset file")
    motion_mode: Optional[str] = Field(default=None, description="Motion effect mode if still image")
    strategy_selected: Optional[str] = Field(default=None, description="Director strategy selected (STOCK_HIGH_CONFIDENCE, GENERATED_IMAGE_PREFERRED, etc.)")
    scene_importance: Optional[str] = Field(default=None, description="Scene importance classification (LOW, NORMAL, HERO)")
    stock_score: Optional[float] = Field(default=None, description="Alias/consolidated stock score")
    stock_candidate: Optional[str] = Field(default=None, description="Identifier or URL of the stock candidate considered")
    generated_attempted: Optional[bool] = Field(default=None, description="Whether AI generation was attempted for this scene")
    still_motion_mode: Optional[str] = Field(default=None, description="Still motion mode if keyframe with motion (zoom_in, zoom_out, etc.)")
    final_visual_source: Optional[str] = Field(default=None, description="Final resolved visual source type (stock, generated_image, image_motion, generated_video)")


class SceneClipInstruction(BaseModel):
    scene_index: int = Field(..., ge=1, description="Scene index")
    material_path: str = Field(..., description="Local path to video clip")
    duration_seconds: float = Field(..., gt=0.0, description="Exact clip duration for this scene")
    fit_mode: str = Field(default="cover", description="Video fit mode (cover, contain, etc.)")
    start_offset: float = Field(default=0.0, ge=0.0, description="Start offset within the source video")
