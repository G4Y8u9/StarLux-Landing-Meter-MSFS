# =========================
# 本项目来自 https://github.com/Starlux531/StarLux-Landing-Meter
# 使用AI Python+SimConnect重写 可以配合MSFS 2020/2024使用
# =========================


import time
import os
import math
from datetime import datetime
from collections import deque, namedtuple
from ctypes import cast, POINTER, c_double

RAD_TO_DEG = 180.0 / math.pi

try:
    from SimConnect import SimConnect
    from SimConnect.Enum import SIMCONNECT_DATATYPE, SIMCONNECT_SIMOBJECT_TYPE
    from SimConnect.Constants import SIMCONNECT_UNUSED
except ImportError:
    # 测试桩环境可能只 stub 了顶层 SimConnect 模块，这里容忍枚举导入失败，
    # 仅保证 SimConnect 本身可用；离线分析路径不使用这些枚举。
    try:
        from SimConnect import SimConnect
    except ImportError:
        print("错误: 缺少依赖库。请在命令行运行 'pip install SimConnect' 安装后再试。")
        exit()
    SIMCONNECT_DATATYPE = None
    SIMCONNECT_SIMOBJECT_TYPE = None
    SIMCONNECT_UNUSED = None

# =========================
# 配置参数
# =========================
FPM_NICE_MAX = 100
FPM_STABLE_MAX = 250
FPM_ATTENTION_MAX = 300

G_NICE_MAX = 1.20
G_STABLE_MAX = 1.50
G_ATTENTION_MAX = 1.80

IMPACT_CAPTURE_MAX_SECONDS = 1.20
PRE_TOUCH_BUFFER_SECONDS = 0.50
PHYSICAL_FPM_WINDOW_SECONDS = 0.25
PHYSICAL_FPM_SHORT_WINDOW_SECONDS = 0.08
PHYSICAL_FPM_PERCENTILE = 0.25
VVI_DIAGNOSTIC_WINDOW_SECONDS = 0.85
G_BASELINE_WINDOW_SECONDS = 0.20
MAX_PAIR_DIFFERENCE_FPM = 60
MIN_PHYSICAL_SAMPLES = 3
MIN_AGL_SAMPLES = 4
MIN_AGL_SPAN_SECONDS = 0.16
MIN_AGL_PAIR_GAP_SECONDS = 0.035
MAX_AGL_SAMPLES = 64
AGL_END_GUARD_SECONDS = 0.04
TERMINAL_AGL_FT = 5.0
# MSFS 数据源修正：视频逐帧比对确认 RADIO HEIGHT / PLANE ALT ABOVE GROUND
# 在接地前存在约 +12.7 ft 的固定偏高（接地前 RA 平台约 12.7 ft，连续多次落地一致），
# 并非真实高度变化。接地确认后把接地前所有离地样本的 RA 统一减去该偏移（不低于 0）
# 再分析，使 0.5 秒聚合轨迹表的 RA 与 AGL 几何链使用修正后的高度。
RA_BIAS_OFFSET_FT = 12.7
# MSFS 适配：修正前 RADIO HEIGHT / PLANE ALT ABOVE GROUND 在触地前约 0.25 s 出现
# ~11.7 ft 平台（接地帧仍读十余英尺、不归零），AGL≤5 ft 终端窗口永远为空。
# 几何闭合链改用更长的 0.85 s 窗口（进近段 AGL 仍与物理下降率吻合）。
AGL_CLOSURE_WINDOW_SECONDS = 0.85
# ---- 拉平曲线参数（对应 Lua 版 FLARE_CONFIG）----
FLARE_START_AGL_FT = 100
FLARE_SAMPLE_INTERVAL_SECONDS = 0.10
FLARE_MAX_SAMPLES = 600
FLARE_BUCKET_SECONDS = 0.50
FLARE_MAX_BUCKETS = 128
FLARE_MIN_SAMPLES = 12
FLARE_MIN_BUCKETS = 4
FLARE_START_DESCENT_FPM = -50
FLARE_START_CONFIRM_SECONDS = 0.20
FLARE_CANCEL_CLIMB_FPM = 100
FLARE_CANCEL_CLIMB_SECONDS = 1.00
FLARE_CANCEL_AGL_FT = 150
FLARE_MAX_TRACE_SECONDS = 120
FLARE_CURVATURE_PERCENTILE = 0.75
FLARE_REVERSAL_NOISE_FPM = 20
FLARE_OSCILLATION_HIGH_REVERSAL_MIN = 3
FLARE_OSCILLATION_SEVERE_REVERSAL_MIN = 5
FLARE_OSCILLATION_EFFICIENCY_MAX = 0.55
FLARE_OSCILLATION_WORSENING_RATIO_MIN = 0.40
GPS_MS_TO_KTS = 1.9438444924406
WIND_MIN_SPEED_KTS = 0.25
BOUNCE_MONITOR_SECONDS = 6.0
BOUNCE_MIN_AIRBORNE_SECONDS = 0.12
BOUNCE_MIN_PEAK_AGL_FT = 0.50
BOUNCE_MIN_UPWARD_MPS = 0.15
BOUNCE_SECOND_G_CAPTURE_SECONDS = 0.35

# ---- G 过载与冲量一致性算法参数（对应 Lua 版 v1.1）----
IMPACT_STOP_VY_MPS = -0.05
IMPACT_STOP_STABLE_FRAMES = 3
G_CURVE_PERCENTILE = 0.75
G_LOCAL_EVENT_WINDOW_SECONDS = 0.160
G_LOCAL_EVENT_MIN_SPAN_SECONDS = 0.040
G_LOCAL_EVENT_MIN_SAMPLES = 5
HIGH_G_DURATION_MIN_SECONDS = 0.030
CONSISTENCY_HIGH_MAX_ERROR = 0.25
CONSISTENCY_MEDIUM_MAX_ERROR = 0.60
# 冲击样本最大合法间隔。16 Hz 下自然采样间隔为 0.0625 s，阈值取约 1.6 倍
# 间隔（0.10 s）：既接受 16 Hz 正常间隔，又拒绝明显断档（避免 G 分析永远
# 误判为"物理样本不足"）。
MAX_VALID_SAMPLE_GAP_SECONDS = 0.10
G_FPM_DECEL_TIME_SECONDS = 0.42
G_FALLBACK_MARGIN_NICE = 0.08
G_FALLBACK_MARGIN_STABLE = 0.12
G_FALLBACK_MARGIN_ATTENTION = 0.16
G_FALLBACK_MARGIN_UNSTABLE = 0.22

# 主循环采样间隔（16 Hz = 1/16 s，精确整除、无浮点误差）。相比 X-Plane 游戏内
# 抓取数据，外部的 SimConnect 库抓取存在精度与延迟差异；实测批量读取约 20~22 Hz，
# 16 Hz 留有充足余量且时间戳对齐更干净。
SAMPLE_INTERVAL_SECONDS = 0.0625
SAMPLE_BUFFER_SIZE = 512
# 16 Hz 下保持约 40 秒的进近历史。
RING_BUFFER_SIZE = 640

Sample = namedtuple(
    'Sample',
    [
        't',
        'on_ground',
        'fpm',
        'local_vy_mps',
        'agl_ft',
        'g_force',
        'ias_kts',
        'tas_kts',
        'pitch_deg',
        'roll_deg',
        'heading_deg',
        'groundspeed_kts',
        'aoa_deg',
        'wind_speed_kts',
        'wind_heading_deg',
    ]
)


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_deg(deg):
    if deg is None:
        return None
    return deg % 360


# GPS 风计算缓存：风向风速变化缓慢，每 0.25 s 计算一次即可，
# 减少每帧的 SimConnect 读取次数（GPS_GROUND_SPEED / GPS_GROUND_*_TRACK / MAGVAR）。
_wind_cache = {'time': -1000.0, 'speed_kts': 0.0, 'heading_deg': 0.0}


def compute_wind_from_gps(aq, heading_deg, tas_kts, now=0.0):
    if now - _wind_cache['time'] < 0.25:
        return _wind_cache['speed_kts'], _wind_cache['heading_deg']
    gps_ground_speed = query_value(aq, 'GPS_GROUND_SPEED')
    if gps_ground_speed is None or heading_deg is None or tas_kts is None:
        return 0.0, 0.0

    gps_track = query_value(aq, 'GPS_GROUND_MAGNETIC_TRACK')
    if gps_track is None:
        gps_track = query_value(aq, 'GPS_GROUND_TRUE_TRACK')
        if gps_track is None:
            return 0.0, 0.0
        magvar = query_value(aq, 'MAGVAR') or 0.0
        gps_track += math.radians(magvar)

    gs_kts = gps_ground_speed * GPS_MS_TO_KTS
    heading_rad = math.radians(heading_deg)
    wind_east = gs_kts * math.sin(gps_track) - tas_kts * math.sin(heading_rad)
    wind_north = gs_kts * math.cos(gps_track) - tas_kts * math.cos(heading_rad)
    wind_speed = math.hypot(wind_east, wind_north)
    if wind_speed < WIND_MIN_SPEED_KTS:
        wind_speed, wind_heading = 0.0, 0.0
    else:
        wind_heading = math.degrees(math.atan2(-wind_east, -wind_north)) % 360
    _wind_cache['time'] = now
    _wind_cache['speed_kts'] = wind_speed
    _wind_cache['heading_deg'] = wind_heading
    return wind_speed, wind_heading


def percentile(values, p):
    if not values:
        return None
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * p
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return sorted_values[lower]
    fraction = rank - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def nearest_rank_percentile(values, p):
    # 与 Lua 版 scratch_percentile 完全一致：索引 = ceil(n × p)，取排序后对应值。
    # 用于 P25 物理速度与 P75 等最近秩分位，而非线性插值。
    if not values:
        return None
    sorted_values = sorted(values)
    index = int(math.ceil(len(sorted_values) * p))
    if index < 1:
        index = 1
    if index > len(sorted_values):
        index = len(sorted_values)
    return sorted_values[index - 1]


def median(values):
    return percentile(values, 0.5)


def round_num(n):
    # 与 Lua 版 round_num 一致：half-away-from-zero（Python round 是银行家舍入，
    # 仅在精确 .5 时差 1，这里统一对齐 Lua 语义）。
    if n >= 0:
        return math.floor(n + 0.5)
    return math.ceil(n - 0.5)


def format_fpm(fpm):
    if fpm is None:
        return "0 fpm"
    rounded = round_num(fpm)
    if rounded >= 0:
        return f"+{rounded} fpm"
    return f"{rounded} fpm"


def vertical_speed_log_text(fpm):
    if fpm is None:
        return "0 fpm"
    rounded = round_num(fpm)
    if rounded >= 0:
        return f"+{rounded} fpm（向上）"
    return f"{rounded} fpm（向下）"


def classify_landing(fpm, max_g_force, external_hint=None):
    abs_fpm = abs(fpm)
    level = 0
    if abs_fpm > FPM_ATTENTION_MAX or max_g_force > G_ATTENTION_MAX:
        level = 3
    elif abs_fpm > FPM_STABLE_MAX or max_g_force > G_STABLE_MAX:
        level = 2
    elif abs_fpm > FPM_NICE_MAX or max_g_force > G_NICE_MAX:
        level = 1

    if level == 3:
        return "UNSTABLE 不良落地"
    if level == 2:
        return "ATTENTION 需注意"
    if level == 1:
        return "STABLE 稳定扎实落地"
    return "NICE 轻柔接地"


def status_short(status):
    if status.startswith("UNSTABLE"):
        return "UNSTABLE"
    if status.startswith("ATTENTION"):
        return "ATTENTION"
    if status.startswith("STABLE"):
        return "STABLE"
    return "NICE"


def status_full_text(status):
    # 弹跳降级说明与报告使用的完整文本（对应 Lua 版 status_short 的完整显示）。
    if status.startswith("UNSTABLE"):
        return "UNSTABLE 不良落地"
    if status.startswith("ATTENTION"):
        return "ATTENTION 需注意"
    if status.startswith("STABLE"):
        return "STABLE 稳定扎实落地"
    return "NICE 轻柔接地"


def status_explanation(status, bounce_result=None):
    # 弹跳降级优先说明降级原因（对应 Lua 版 status_explanation 的弹跳分支）。
    if bounce_result is not None and bounce_result.get('score_applied'):
        original = bounce_result.get('original_status')
        if original is not None and status_short(original) != status_short(status):
            if status.startswith("UNSTABLE"):
                return "发生弹跳，且至少一次稳健过载超过 1.80 G"
            return f"发生弹跳：评级由 {status_full_text(original)} 降级为 {status_full_text(status)}"
    if status.startswith("UNSTABLE"):
        return "不良落地：FPM 或 G 超出 Attention 上限。"
    if status.startswith("ATTENTION"):
        return "需注意：FPM 或 G 达到 Attention 等级。"
    if status.startswith("STABLE"):
        return "稳定扎实落地：落地平稳但仍有改进空间。"
    return "轻柔接地：下降率和过载都在 Nice 范围内。"


def confidence_level_text(level):
    # 对应 Lua 版 confidence_text：HIGH/MEDIUM/LOW → 高/中/低。
    if level == "HIGH":
        return "高"
    if level == "MEDIUM":
        return "中"
    return "低"


def estimated_runway_from_heading(heading_deg):
    if heading_deg is None:
        return "--"
    normalized = heading_deg % 360
    runway = int((normalized + 5) / 10)
    if runway == 0 or runway == 36:
        runway = 36
    elif runway > 36:
        runway -= 36
    return f"{runway:02d}"


def angular_diff_180(from_deg, to_deg):
    # 飞机航向到来风方向之间带正负号的最短角度差（负=风从左侧，正=风从右侧）。
    diff = (from_deg - to_deg) % 360
    if diff > 180:
        diff -= 360
    return diff


def build_wind_relative_text(wind_from_deg, wind_speed_kts, aircraft_heading_deg):
    # 对应 Lua 版：六类相对风（顶风/左前侧风/右前侧风/左后侧风/右后侧风/顺风）。
    if wind_from_deg is None or aircraft_heading_deg is None:
        return "风 --"
    diff = angular_diff_180(wind_from_deg, aircraft_heading_deg)
    abs_diff = abs(diff)
    if abs_diff <= 20:
        side = "顶风"
    elif abs_diff >= 160:
        side = "顺风"
    elif diff < 0 and abs_diff <= 90:
        side = "左前侧风"
    elif diff > 0 and abs_diff <= 90:
        side = "右前侧风"
    elif diff < 0:
        side = "左后侧风"
    else:
        side = "右后侧风"
    speed = round_num(wind_speed_kts or 0.0)
    return f"风 {round_num(normalize_deg(wind_from_deg)):03d}/{speed}kt {side}"


def roll_log_text(roll_deg):
    # 对应 Lua 版：左倾/右倾/水平（很小的数值按水平处理）。
    if roll_deg is None:
        roll_deg = 0.0
    abs_roll = abs(roll_deg)
    if abs_roll < 0.05:
        return "水平（0.0 deg）"
    elif roll_deg < 0:
        return f"左倾 {abs_roll:.1f} deg"
    return f"右倾 {abs_roll:.1f} deg"


def collect_samples(samples, start_time, end_time, predicate=None):
    return [s for s in samples if start_time <= s.t <= end_time and (predicate is None or predicate(s))]


def terminal_window_values(samples, touch_time, value_kind):
    # MSFS 适配：X-Plane 的 AGL 在触地前会真实降到 5 ft 以下，而 MSFS 的
    # RADIO HEIGHT / PLANE ALT ABOVE GROUND 在最后约 11.7 ft 处出现平台
    # （接地帧仍读十余英尺、不归零），导致"AGL≤5 ft"窗口永远为空。
    # 因此终端窗口改为纯时间窗（触地前 250 ms、离地样本），不依赖 AGL 门限。
    start_time = touch_time - PHYSICAL_FPM_WINDOW_SECONDS
    end_time = touch_time - AGL_END_GUARD_SECONDS
    values = []
    for s in samples:
        if s.on_ground:
            continue
        if s.t < start_time or s.t > end_time:
            continue
        if value_kind == 'local_vy' and s.local_vy_mps is not None:
            values.append(s.local_vy_mps)
        elif value_kind == 'vvi' and s.fpm is not None:
            values.append(s.fpm)
    return values


def compute_physical_fpm(samples, touch_time):
    # 对应 Lua 版 collect_terminal_fpm_values("local_vy") + scratch_percentile(P25)。
    values = [v * 196.850394 for v in terminal_window_values(samples, touch_time, 'local_vy')]
    sample_count = len(values)
    valid = sample_count >= MIN_PHYSICAL_SAMPLES
    if not values:
        return None, sample_count, valid
    return nearest_rank_percentile(values, PHYSICAL_FPM_PERCENTILE), sample_count, valid


def compute_short_physical_median(samples, start_time, end_time):
    # 与 Lua 版一致：80 ms 短窗中位数只在样本数 >= 2 时采用（单样本视为无效）。
    values = [s.local_vy_mps * 196.850394 for s in samples if start_time <= s.t <= end_time and not s.on_ground and s.local_vy_mps is not None]
    if len(values) < 2:
        return None
    return median(values)


def compute_vvi_metrics(samples, touch_time, approach_fallback=None):
    # 对应 Lua 版 collect_terminal_fpm_values("vvi") 中位数。
    terminal_values = terminal_window_values(samples, touch_time, 'vvi')
    sample_count = len(terminal_values)
    median_vvi = median(terminal_values) if terminal_values else None
    # 对应 Lua 版 select_min_vvi_fpm：最差 VVI = min(进近快照, 0.85s 窗口内最小值)。
    diagnostic_values = [s.fpm for s in samples if not s.on_ground and touch_time - VVI_DIAGNOSTIC_WINDOW_SECONDS <= s.t <= touch_time and s.fpm is not None]
    if approach_fallback is not None:
        diagnostic_values = diagnostic_values + [approach_fallback]
    min_vvi = min(diagnostic_values) if diagnostic_values else None
    return median_vvi, min_vvi, sample_count, sample_count >= 3


def compute_agl_closure_fpm(samples, touch_time):
    # MSFS 适配：进近段 AGL 与物理下降率吻合（实测 16.45→12.19 ft ≈ -194 fpm），
    # 但触地前最后约 0.25 s 出现 ~11.7 ft 平台。因此几何闭合斜率用更长的
    # 0.85 s 窗口计算，覆盖平台出现前的准确段。
    start_time = touch_time - AGL_CLOSURE_WINDOW_SECONDS
    end_time = touch_time - AGL_END_GUARD_SECONDS
    points = [s for s in samples if not s.on_ground and start_time <= s.t <= end_time and s.agl_ft is not None]
    points.sort(key=lambda s: s.t)
    if len(points) < MIN_AGL_SAMPLES:
        return None, len(points), 0.0, 0

    if len(points) > MAX_AGL_SAMPLES:
        points = points[:MAX_AGL_SAMPLES]

    span = points[-1].t - points[0].t
    if span < MIN_AGL_SPAN_SECONDS:
        return None, len(points), span, 0

    slopes = []
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            dt = points[j].t - points[i].t
            if dt < MIN_AGL_PAIR_GAP_SECONDS:
                continue
            d_agl = points[j].agl_ft - points[i].agl_ft
            slopes.append(d_agl / dt)

    if len(slopes) < 3:
        return None, len(points), span, len(slopes)

    # 与 Lua 版一致：阈值判定在 m/s 上进行（-20 ~ +3 m/s），换算为 fpm 后再返回。
    slope_mps = median(slopes) / 3.28084
    if slope_mps is None or slope_mps < -20 or slope_mps > 3:
        return None, len(points), span, len(slopes)

    agl_fpm = slope_mps * 196.850394
    return agl_fpm, len(points), span, len(slopes)


def sanitize_g(g):
    # 与 Lua 版一致：仅保留 0.2 < G ≤ 5.0 的样本，更极端的值视为损坏。
    if g is None:
        return None
    if 0.2 < g <= 5.0:
        return g
    return None


def projected_vertical_g(sample):
    # 与 Lua 版一致：projectedG = rawNormalG × cos(pitch°) × cos(roll°)。
    # 先做损坏样本过滤（0.2 < G ≤ 5.0），防止 MSFS 偶发的异常 G 读数
    # （如脉冲到数十 G）污染峰值/局部包络/冲量一致性计算。
    g = sanitize_g(sample.g_force)
    if g is None:
        return None
    return g * math.cos(math.radians(sample.pitch_deg)) * math.cos(math.radians(sample.roll_deg))


def fallback_g_cap(fpm):
    # 与 Lua 版一致：样本无效时的备用一致性 G 上限。
    abs_fpm = abs(fpm)
    margin = G_FALLBACK_MARGIN_UNSTABLE
    if abs_fpm <= FPM_NICE_MAX:
        margin = G_FALLBACK_MARGIN_NICE
    elif abs_fpm <= FPM_STABLE_MAX:
        margin = G_FALLBACK_MARGIN_STABLE
    elif abs_fpm <= FPM_ATTENTION_MAX:
        margin = G_FALLBACK_MARGIN_ATTENTION
    sink_mps = abs_fpm * 0.00508
    return 1.0 + sink_mps / (G_FPM_DECEL_TIME_SECONDS * 9.80665) + margin


def collect_projected_g_values(samples, start_time, end_time, airborne_only=False):
    values = []
    for s in samples:
        if s.t < start_time or s.t > end_time:
            continue
        if airborne_only and s.on_ground:
            continue
        pg = projected_vertical_g(s)
        if pg is not None:
            values.append(pg)
    return values


def collect_local_vy_values(samples, start_time, end_time, airborne_only=False):
    values = []
    for s in samples:
        if s.t < start_time or s.t > end_time:
            continue
        if airborne_only and s.on_ground:
            continue
        if s.local_vy_mps is not None:
            values.append(s.local_vy_mps)
    return values


def determine_impact_capture(samples, touch_time):
    # 复现 Lua 版 begin_landing_analysis / process_landing_analysis 的采集状态机：
    # 垂直速度反向 >0.05 m/s、连续三帧进入稳定区（≥ -0.05 m/s）、或达到 1.20 s 安全上限。
    impact_start = touch_time
    pre_samples = [s for s in samples if s.t < touch_time]
    if pre_samples:
        last = pre_samples[-1]
        if (not last.on_ground and touch_time - last.t > 0
                and touch_time - last.t <= MAX_VALID_SAMPLE_GAP_SECONDS):
            impact_start = last.t

    capture_end_reason = "等待采集"
    impact_end = touch_time
    end_time = touch_time
    stop_stable_frames = 0
    stop_candidate_time = 0
    window = sorted(
        [s for s in samples if touch_time <= s.t <= touch_time + IMPACT_CAPTURE_MAX_SECONDS],
        key=lambda s: s.t,
    )
    for s in window:
        vy = s.local_vy_mps
        if vy is None:
            continue
        if vy >= IMPACT_STOP_VY_MPS:
            if stop_stable_frames == 0:
                stop_candidate_time = s.t
            stop_stable_frames += 1
        else:
            stop_stable_frames = 0
            stop_candidate_time = 0

        if vy > 0.05:
            capture_end_reason = "检测到垂直速度反向"
            impact_end = s.t
            end_time = s.t
            return impact_start, impact_end, end_time, capture_end_reason
        if stop_stable_frames >= IMPACT_STOP_STABLE_FRAMES:
            capture_end_reason = "垂直速度连续三帧进入稳定区"
            impact_end = stop_candidate_time
            end_time = s.t
            return impact_start, impact_end, end_time, capture_end_reason

    capture_end_reason = "达到1.20秒安全采集上限"
    impact_end = touch_time + IMPACT_CAPTURE_MAX_SECONDS
    end_time = touch_time + IMPACT_CAPTURE_MAX_SECONDS
    return impact_start, impact_end, end_time, capture_end_reason


def calculate_local_event_g(samples, start_time, end_time, curve_g):
    # 复现 Lua 版 log_tools.calculate_local_event_g：在压缩区间内寻找最强的
    # 160ms 局部 P75 包络，保留持续数帧的真实冲击而避免单帧尖峰接管结果。
    best_g = None
    best_start = 0
    best_end = 0
    best_span = 0
    best_count = 0
    best_index = 0

    window_samples = sorted(
        [s for s in samples if start_time <= s.t <= end_time],
        key=lambda s: s.t,
    )
    for i, first_sample in enumerate(window_samples):
        window_end = min(end_time, first_sample.t + G_LOCAL_EVENT_WINDOW_SECONDS)
        values = []
        first_valid_time = None
        last_valid_time = None
        for s in window_samples[i:]:
            if s.t > window_end:
                break
            pg = projected_vertical_g(s)
            if pg is not None:
                values.append(pg)
                if first_valid_time is None:
                    first_valid_time = s.t
                last_valid_time = s.t
        if not values:
            continue
        span = last_valid_time - first_valid_time if first_valid_time is not None else 0.0
        if len(values) >= G_LOCAL_EVENT_MIN_SAMPLES and span >= G_LOCAL_EVENT_MIN_SPAN_SECONDS:
            event_g = nearest_rank_percentile(values, G_CURVE_PERCENTILE)
            if event_g is not None and (best_g is None or event_g > best_g):
                best_g = event_g
                best_start = first_valid_time
                best_end = last_valid_time
                best_span = span
                best_count = len(values)
                best_index = max(1, int(math.ceil(len(values) * G_CURVE_PERCENTILE)))

    local_event_g_valid = best_g is not None
    local_event_g = best_g if best_g is not None else curve_g
    return {
        'local_event_g_valid': local_event_g_valid,
        'local_event_g': local_event_g,
        'local_event_window_start_time': best_start,
        'local_event_window_end_time': best_end,
        'local_event_window_span_seconds': best_span,
        'local_event_sample_count': best_count,
        'local_event_percentile_index': best_index,
        'robust_event_g': max(curve_g, local_event_g),
    }


def analyze_landing_g(samples, touch_time, touchdown_sample, selected_fpm,
                      physical_fpm_valid, physical_fpm, vvi_fpm):
    # 完整复现 Lua 版 analyze_landing_velocity 的 G 部分 + analyze_landing_impulse。
    impact_start, impact_end, end_time, capture_end_reason = determine_impact_capture(samples, touch_time)

    # 冲量起点速度：优先 80ms 短窗中位数，其次 250ms 物理 P25，最后 VVI 换算。
    short_values = collect_local_vy_values(
        samples,
        touch_time - PHYSICAL_FPM_SHORT_WINDOW_SECONDS,
        touch_time,
        airborne_only=True,
    )
    if len(short_values) >= 2:
        pre_vy_mps = median(short_values)
    elif physical_fpm_valid and physical_fpm is not None:
        pre_vy_mps = physical_fpm / 196.850394
    else:
        pre_vy_mps = (vvi_fpm or 0.0) * 0.00508

    # 接地前垂直投影 G 基线（中位数，仅离地样本）。
    baseline_values = collect_projected_g_values(
        samples,
        touch_time - G_BASELINE_WINDOW_SECONDS,
        impact_start,
        airborne_only=True,
    )
    baseline_g = median(baseline_values) if baseline_values else 1.0

    # 压缩末端速度（最后 50ms，包含接地后样本，与 Lua 一致）。
    post_values = collect_local_vy_values(
        samples,
        max(touch_time, end_time - 0.05),
        end_time,
        airborne_only=False,
    )
    post_vy_mps = median(post_values) if post_values else 0.0
    velocity_delta_mps = max(0.0, post_vy_mps - pre_vy_mps)
    stop_duration_seconds = max(0.03, impact_end - impact_start)

    # 第一次压缩投影 G 曲线与局部包络。
    impact_g_values = collect_projected_g_values(samples, impact_start, impact_end, airborne_only=False)
    impact_sample_count = len(impact_g_values)
    touch_g = sanitize_g(touchdown_sample.g_force) or 1.0
    curve_g = nearest_rank_percentile(impact_g_values, G_CURVE_PERCENTILE) if impact_g_values else touch_g
    peak_g = touch_g
    if impact_g_values:
        peak_g = max(peak_g, max(impact_g_values))
    local_event = calculate_local_event_g(samples, impact_start, impact_end, curve_g)
    robust_event_g = local_event['robust_event_g']

    # 冲量梯形积分与高 G 持续时间。
    high_threshold = baseline_g + max(0.0, peak_g - baseline_g) * 0.80
    impulse_delta = 0.0
    high_duration = 0.0
    max_gap = 0.0
    gap_sum = 0.0
    gap_count = 0
    previous_t = None
    previous_g = None
    ordered = sorted([s for s in samples if impact_start <= s.t <= impact_end], key=lambda s: s.t)
    for s in ordered:
        current_g = projected_vertical_g(s)
        if current_g is None:
            continue
        if previous_t is not None:
            dt = s.t - previous_t
            max_gap = max(max_gap, dt)
            if 0 < dt <= 0.10:
                gap_sum += dt
                gap_count += 1
                previous_excess = max(0.0, previous_g - baseline_g)
                current_excess = max(0.0, current_g - baseline_g)
                impulse_delta += (previous_excess + current_excess) * 0.5 * 9.80665 * dt
                if previous_g >= high_threshold and current_g >= high_threshold:
                    high_duration += dt
        previous_t = s.t
        previous_g = current_g

    average_sample_gap = gap_sum / gap_count if gap_count > 0 else 0.0
    consistency_error = abs(impulse_delta - velocity_delta_mps) / max(velocity_delta_mps, 0.20)

    equivalent_g = baseline_g + velocity_delta_mps / (9.80665 * stop_duration_seconds)
    equivalent_g = max(1.0, min(5.0, equivalent_g))

    samples_valid = (physical_fpm_valid and impact_sample_count >= 3
                     and max_gap <= MAX_VALID_SAMPLE_GAP_SECONDS)

    if not samples_valid:
        confidence = "LOW"
        used_fallback = True
        method = "物理样本不足，使用备用一致性上限"
        landing_g = min(curve_g, fallback_g_cap(selected_fpm))
    elif consistency_error <= CONSISTENCY_HIGH_MAX_ERROR and high_duration >= HIGH_G_DURATION_MIN_SECONDS:
        confidence = "HIGH"
        used_fallback = False
        method = "高可信冲量，采用第75百分位曲线G"
        landing_g = curve_g
    elif consistency_error <= CONSISTENCY_MEDIUM_MAX_ERROR and high_duration > 0:
        confidence = "MEDIUM"
        used_fallback = False
        method = ("中可信冲量，采用全局P75与160ms局部冲击包络的较大值"
                  if local_event['local_event_g_valid'] else
                  "中可信冲量，局部包络样本不足，采用全局第75百分位曲线G")
        landing_g = robust_event_g
    else:
        confidence = "LOW"
        used_fallback = False
        method = "低可信峰值，主要采用冲量等效G"
        landing_g = curve_g * 0.25 + equivalent_g * 0.75

    # 达到安全采集上限表示长行程起落架仍未完全稳定，不能宣称高可信。
    if capture_end_reason == "达到1.20秒安全采集上限":
        confidence = "MEDIUM"
        used_fallback = False
        method = ("长行程压缩达到采集上限，采用全局P75与160ms局部冲击包络的较大值"
                  if local_event['local_event_g_valid'] else
                  "长行程压缩达到采集上限，局部包络样本不足，采用全局第75百分位曲线G")
        landing_g = robust_event_g

    landing_g = max(1.0, min(5.0, landing_g))

    return {
        'landing_g': landing_g,
        'landing_touch_g': touch_g,
        'landing_peak_g': peak_g,
        'landing_curve_g': curve_g,
        'landing_baseline_g': baseline_g,
        'landing_local_event_g': local_event['local_event_g'],
        'landing_local_event_g_valid': local_event['local_event_g_valid'],
        'landing_robust_g': robust_event_g,
        'landing_equivalent_g': equivalent_g,
        'landing_impulse_delta_mps': impulse_delta,
        'landing_velocity_delta_mps': velocity_delta_mps,
        'landing_high_g_duration_seconds': high_duration,
        'landing_max_sample_gap_seconds': max_gap,
        'landing_average_sample_gap_seconds': average_sample_gap,
        'landing_consistency_error': consistency_error,
        'landing_g_confidence': confidence,
        'landing_g_method': method,
        'landing_used_fallback': used_fallback,
        'landing_impact_sample_count': impact_sample_count,
        'landing_capture_end_reason': capture_end_reason,
        'landing_stop_duration_seconds': stop_duration_seconds,
    }


def reconstruct_flare_trace(samples, touch_time):
    # 复现 Lua 版 update_flare_trace / start_flare_trace / add_flare_trace_sample
    # 的下降确认与爬升取消状态机，返回触地前按 10 Hz 采样的拉平轨迹样本。
    active = False
    start_time = 0.0
    next_sample_time = 0.0
    descent_confirm_start = 0.0
    climb_confirm_start = 0.0
    limited = False
    trace_samples = []

    ordered = sorted((s for s in samples if s.t <= touch_time), key=lambda s: s.t)
    for s in ordered:
        now = s.t
        radio_alt_ft = s.agl_ft
        on_ground = s.on_ground
        physical_fpm = (s.local_vy_mps * 196.850394) if s.local_vy_mps is not None else 0.0
        vvi_fpm = s.fpm if s.fpm is not None else 0.0
        armed = True  # 进近阶段视为已进入待触发状态

        descending = (not on_ground
                      and physical_fpm <= FLARE_START_DESCENT_FPM
                      and vvi_fpm <= FLARE_START_DESCENT_FPM)

        # 已启动的轨迹：重新爬升、飞离近地范围或持续时间异常则作废。
        if active:
            climbing = (physical_fpm >= FLARE_CANCEL_CLIMB_FPM
                        and vvi_fpm >= FLARE_CANCEL_CLIMB_FPM)
            if climbing:
                if climb_confirm_start <= 0:
                    climb_confirm_start = now
            else:
                climb_confirm_start = 0
            climb_confirmed = (climb_confirm_start > 0
                               and now - climb_confirm_start >= FLARE_CANCEL_CLIMB_SECONDS)
            trace_timed_out = start_time > 0 and now - start_time > FLARE_MAX_TRACE_SECONDS
            if (radio_alt_ft is not None and radio_alt_ft >= FLARE_CANCEL_AGL_FT) \
                    or climb_confirmed or trace_timed_out:
                active = False
                start_time = 0.0
                next_sample_time = 0.0
                descent_confirm_start = 0.0
                climb_confirm_start = 0.0
                trace_samples = []

        # 未启动：须先确认持续下降 0.2 秒，且高度不高于 100 ft，防止起飞爬升误启动。
        if not active and armed and not on_ground:
            if descending:
                if descent_confirm_start <= 0:
                    descent_confirm_start = now
            else:
                descent_confirm_start = 0
            descent_confirmed = (descent_confirm_start > 0
                                 and now - descent_confirm_start >= FLARE_START_CONFIRM_SECONDS)
            if (descent_confirmed and radio_alt_ft is not None
                    and radio_alt_ft <= FLARE_START_AGL_FT and radio_alt_ft >= 0):
                active = True
                start_time = now
                next_sample_time = now
                descent_confirm_start = 0.0
                climb_confirm_start = 0.0
                trace_samples = []

        # 固定 10 Hz 采样。
        if active and not on_ground and now >= next_sample_time:
            if len(trace_samples) >= FLARE_MAX_SAMPLES:
                limited = True
                next_sample_time = now + FLARE_SAMPLE_INTERVAL_SECONDS
            else:
                trace_samples.append(s)
                next_sample_time = now + FLARE_SAMPLE_INTERVAL_SECONDS

    return {
        'samples': trace_samples,
        'start_time': start_time,
        'touch_time': touch_time,
        'limited': limited,
    }


def build_flare_buckets(trace_samples, start_time, touch_time, selected_fpm_source,
                        landing_fpm, touchdown_sample, physical_fpm, vvi_fpm,
                        physical_fpm_valid):
    # 复现 Lua 版 analyze_flare_curve 的 0.5 秒分桶聚合与触地桶处理。
    if start_time <= 0 or not trace_samples:
        return [], False, 0

    bucket_map = {}
    limited = False
    for s in trace_samples:
        bucket_index = int(math.floor((s.t - start_time) / FLARE_BUCKET_SECONDS)) + 1
        if bucket_index < 1:
            bucket_index = 1
        if bucket_index > FLARE_MAX_BUCKETS:
            bucket_index = FLARE_MAX_BUCKETS
            limited = True
        bucket = bucket_map.setdefault(bucket_index, {
            'count': 0,
            't': 0.0,
            'agl_ft': 0.0,
            'vvi_fpm': 0.0,
            'physical_fpm': 0.0,
            'ias_kts': 0.0,
            'gs_kts': 0.0,
            'pitch_deg': 0.0,
            'aoa_deg': 0.0,
            'roll_deg': 0.0,
            'selected_fpm': 0.0,
        })
        bucket['count'] += 1
        bucket['t'] += s.t
        bucket['agl_ft'] += s.agl_ft or 0.0
        bucket['vvi_fpm'] += s.fpm or 0.0
        bucket['physical_fpm'] += (s.local_vy_mps * 196.850394) if s.local_vy_mps is not None else 0.0
        bucket['ias_kts'] += s.ias_kts
        bucket['gs_kts'] += s.groundspeed_kts
        bucket['pitch_deg'] += s.pitch_deg
        bucket['roll_deg'] += s.roll_deg
        bucket['selected_fpm'] += selected_fpm_source(s)
        bucket['aoa_deg'] += s.aoa_deg

    buckets = []
    for index in sorted(bucket_map):
        bucket = bucket_map[index]
        count = bucket['count']
        if count > 0:
            bucket['t'] /= count
            bucket['agl_ft'] /= count
            bucket['vvi_fpm'] /= count
            bucket['physical_fpm'] /= count
            bucket['ias_kts'] /= count
            bucket['gs_kts'] /= count
            bucket['pitch_deg'] /= count
            bucket['aoa_deg'] /= count
            bucket['roll_deg'] /= count
            bucket['selected_fpm'] /= count
        buckets.append(bucket)

    # 触地 FPM 作为轨迹终点：与末桶太近则直接替换末桶，否则追加触地桶。
    touch_physical_fpm = physical_fpm if (physical_fpm_valid and physical_fpm is not None) else (vvi_fpm or 0.0)
    if buckets and touch_time - buckets[-1]['t'] >= 0.15 and len(buckets) < FLARE_MAX_BUCKETS:
        buckets.append({
            'count': 1,
            't': touch_time,
            'agl_ft': 0.0,
            'physical_fpm': touch_physical_fpm,
            'vvi_fpm': vvi_fpm or 0.0,
            'selected_fpm': landing_fpm,
            'ias_kts': touchdown_sample.ias_kts,
            'gs_kts': touchdown_sample.groundspeed_kts,
            'pitch_deg': touchdown_sample.pitch_deg,
            'aoa_deg': touchdown_sample.aoa_deg,
            'roll_deg': touchdown_sample.roll_deg,
        })
    elif buckets:
        last = buckets[-1]
        last['t'] = touch_time
        last['agl_ft'] = 0.0
        last['physical_fpm'] = touch_physical_fpm
        last['vvi_fpm'] = vvi_fpm or 0.0
        last['selected_fpm'] = landing_fpm

    return buckets, limited, len(trace_samples)


def analyze_flare_curve(buckets, start_time, touch_time, raw_count=0):
    # 复现 Lua 版 analyze_flare_curve：最近秩 P75 曲率 + 反转/恶化/改善指标 + 震荡判定。
    result = {
        'valid': False,
        'metric': 0.0,
        'signed_mean_curvature': 0.0,
        'duration_seconds': max(0.0, touch_time - start_time) if start_time > 0 else 0.0,
        'entry_fpm': 0.0,
        'touchdown_fpm': 0.0,
        'recovery_fpm': 0.0,
        'reversal_count': 0,
        'worsening_ratio': 0.0,
        'monotonic_efficiency': 0.0,
        'late_recovery_ratio': 0.0,
        'trend_text': '拉平轨迹样本不足',
        'calculation_ms': 0.0,
    }

    if start_time <= 0 or raw_count < FLARE_MIN_SAMPLES:
        result['trend_text'] = '拉平轨迹样本不足'
        return result
    if len(buckets) < FLARE_MIN_BUCKETS:
        result['trend_text'] = '拉平轨迹聚合点不足'
        return result

    entry_fpm = buckets[0]['selected_fpm']
    touch_fpm = buckets[-1]['selected_fpm']
    total_variation = 0.0
    worsening_count = 0
    reversal_count = 0
    previous_direction = 0

    # 相邻聚合点下降率变化：超过 ±20 fpm 才算方向；恶化（delta<-20）计数。
    for i in range(1, len(buckets)):
        delta = buckets[i]['selected_fpm'] - buckets[i - 1]['selected_fpm']
        total_variation += abs(delta)
        direction = 0
        if delta > FLARE_REVERSAL_NOISE_FPM:
            direction = 1
        elif delta < -FLARE_REVERSAL_NOISE_FPM:
            direction = -1
            worsening_count += 1
        if direction != 0 and previous_direction != 0 and direction != previous_direction:
            reversal_count += 1
        if direction != 0:
            previous_direction = direction

    # 二阶曲率：|二阶变化| 第 75 百分位（最近秩，与 Lua scratch_percentile 一致）。
    curve_samples = []
    signed_sum = 0.0
    curvature_count = 0
    for i in range(2, len(buckets)):
        p1 = buckets[i - 2]
        p2 = buckets[i - 1]
        p3 = buckets[i]
        dt1 = p2['t'] - p1['t']
        dt2 = p3['t'] - p2['t']
        if dt1 > 0.10 and dt2 > 0.10:
            slope1 = (p2['selected_fpm'] - p1['selected_fpm']) / dt1
            slope2 = (p3['selected_fpm'] - p2['selected_fpm']) / dt2
            curvature = (slope2 - slope1) / ((dt1 + dt2) * 0.5)
            curve_samples.append(abs(curvature))
            signed_sum += curvature
            curvature_count += 1

    recovery = touch_fpm - entry_fpm
    interval_count = max(1, len(buckets) - 1)
    late_target_time = start_time + result['duration_seconds'] * 0.70
    late_reference_fpm = entry_fpm
    for b in buckets:
        if b['t'] <= late_target_time:
            late_reference_fpm = b['selected_fpm']

    result['valid'] = curvature_count > 0
    result['metric'] = nearest_rank_percentile(curve_samples, FLARE_CURVATURE_PERCENTILE) if curve_samples else 0.0
    result['signed_mean_curvature'] = signed_sum / curvature_count if curvature_count > 0 else 0.0
    result['entry_fpm'] = entry_fpm
    result['touchdown_fpm'] = touch_fpm
    result['recovery_fpm'] = recovery
    result['reversal_count'] = reversal_count
    result['worsening_ratio'] = worsening_count / interval_count
    result['monotonic_efficiency'] = (recovery / max(total_variation, 1.0)) if recovery > 0 else 0.0
    result['late_recovery_ratio'] = (max(0.0, touch_fpm - late_reference_fpm) / recovery) if recovery > 20 else 0.0

    # 震荡判定：达到 5 次明显反转，或 3 次反转并伴随较低改善效率/较高恶化占比。
    oscillation_high = (
        reversal_count >= FLARE_OSCILLATION_SEVERE_REVERSAL_MIN
        or (
            reversal_count >= FLARE_OSCILLATION_HIGH_REVERSAL_MIN
            and (
                result['monotonic_efficiency'] < FLARE_OSCILLATION_EFFICIENCY_MAX
                or result['worsening_ratio'] >= FLARE_OSCILLATION_WORSENING_RATIO_MIN
            )
        )
    )
    if oscillation_high:
        result['trend_text'] = '下降率轨迹震荡高'
    else:
        result['trend_text'] = '下降率轨迹正常'
    return result


def analyze_bounce_in_samples(samples, first_touch_time):
    # 完整复现 Lua 版 begin_bounce_monitor / process_bounce_monitor /
    # finish_second_touch_analysis 的离线版本：
    # 第一次触地后任一离地样本进入离地阶段；第二次接地时按
    # 持续离地时间 >= 0.12 s 且（峰值 AGL >= 0.50 ft 或峰值向上速度 >= 0.15 m/s）判定弹跳。
    # second_fpm 取第二次触地前 250 ms 离地物理速度 P25；
    # second_curve_g 取第二次压缩 0.35 s 窗口内垂直投影 G 的 P75（clamp 1..5）。
    result = {
        'detected': False,
        'first_touch_time': first_touch_time,
        'second_touch_time': None,
        'airborne_duration_seconds': 0.0,
        'airborne_peak_agl_ft': 0.0,
        'airborne_peak_upward_mps': 0.0,
        'second_fpm': None,
        'second_touch_g': None,
        'second_peak_g': None,
        'second_curve_g': None,
        'second_g_ready': False,
        'monitor_complete': False,
        'original_status': None,
        'score_applied': False,
    }
    monitor_until = first_touch_time + BOUNCE_MONITOR_SECONDS
    ordered = sorted(
        (s for s in samples if first_touch_time < s.t <= monitor_until),
        key=lambda s: s.t,
    )

    phase = 'waiting'
    airborne_start = 0.0
    peak_agl = 0.0
    peak_upward = 0.0
    prev_on_ground = True  # 触地帧处于接地状态（对应 Lua was_on_ground 初值）

    for s in ordered:
        if phase == 'second_capture':
            clean_g = sanitize_g(s.g_force)
            if clean_g is not None:
                if result['second_peak_g'] is None or clean_g > result['second_peak_g']:
                    result['second_peak_g'] = clean_g
            if s.t >= result['second_touch_time'] + BOUNCE_SECOND_G_CAPTURE_SECONDS:
                phase = 'complete'
                break
            continue
        if phase == 'waiting':
            if not s.on_ground and prev_on_ground:
                phase = 'airborne'
                airborne_start = s.t
                peak_agl = max(0.0, s.agl_ft or 0.0)
                peak_upward = max(0.0, s.local_vy_mps or 0.0)
        elif phase == 'airborne':
            if not s.on_ground:
                peak_agl = max(peak_agl, s.agl_ft or 0.0)
                peak_upward = max(peak_upward, s.local_vy_mps or 0.0)
            elif not prev_on_ground:
                duration = max(0.0, s.t - airborne_start)
                valid = (
                    duration >= BOUNCE_MIN_AIRBORNE_SECONDS
                    and (
                        peak_agl >= BOUNCE_MIN_PEAK_AGL_FT
                        or peak_upward >= BOUNCE_MIN_UPWARD_MPS
                    )
                )
                if valid:
                    result['detected'] = True
                    result['second_touch_time'] = s.t
                    result['airborne_duration_seconds'] = duration
                    result['airborne_peak_agl_ft'] = peak_agl
                    result['airborne_peak_upward_mps'] = peak_upward
                    fpm_values = [
                        u.local_vy_mps * 196.850394
                        for u in samples
                        if not u.on_ground
                        and s.t - PHYSICAL_FPM_WINDOW_SECONDS <= u.t <= s.t
                        and u.local_vy_mps is not None
                    ]
                    if fpm_values:
                        result['second_fpm'] = round_num(nearest_rank_percentile(fpm_values, PHYSICAL_FPM_PERCENTILE))
                    elif s.local_vy_mps is not None:
                        result['second_fpm'] = round_num(s.local_vy_mps * 196.850394)
                    touch_g = sanitize_g(s.g_force) or 1.0
                    result['second_touch_g'] = touch_g
                    result['second_peak_g'] = touch_g
                    result['second_curve_g'] = touch_g
                    phase = 'second_capture'
                else:
                    phase = 'waiting'
                    airborne_start = 0.0
                    peak_agl = 0.0
                    peak_upward = 0.0
        prev_on_ground = s.on_ground
        if phase == 'complete':
            break

    result['monitor_complete'] = phase == 'complete' or not ordered

    # 第二次压缩 P75 投影 G：无论采集窗口是否在样本内完整走完都计算
    # （样本提前耗尽时用已有的 0.35 s 窗口样本）。
    if result['detected']:
        capture_end = result['second_touch_time'] + BOUNCE_SECOND_G_CAPTURE_SECONDS
        g_values = [
            projected_vertical_g(u)
            for u in ordered
            if result['second_touch_time'] <= u.t <= capture_end
        ]
        g_values = [g for g in g_values if g is not None]
        if g_values:
            result['second_curve_g'] = max(1.0, min(5.0, nearest_rank_percentile(g_values, G_CURVE_PERCENTILE)))
        else:
            result['second_curve_g'] = result['second_touch_g'] or 1.0
        result['second_g_ready'] = True
        result['monitor_complete'] = True

    return result


def apply_bounce_score(status, bounce_result, landing_g):
    # 复现 Lua 版 apply_bounce_score：弹跳成立后
    # Nice→Stable、Stable→Attention、Attention 保持；
    # 任一次稳健 G（第一次最终 G 或第二次触地 P75）超过 1.80 直接判 UNSTABLE。
    if not bounce_result.get('detected') or not bounce_result.get('second_g_ready'):
        return status, False
    second_curve_g = bounce_result.get('second_curve_g')
    if (
        status.startswith('UNSTABLE')
        or landing_g > G_ATTENTION_MAX
        or (second_curve_g is not None and second_curve_g > G_ATTENTION_MAX)
    ):
        return 'UNSTABLE 不良落地', True
    if status.startswith('NICE'):
        return 'STABLE 稳定扎实落地', True
    if status.startswith('STABLE'):
        return 'ATTENTION 需注意', True
    return status, True  # Attention 发生弹跳后仍保持 Attention


def update_live_bounce(bounce, sample):
    # 复现 Lua 版 process_bounce_monitor 的增量状态机，供主循环逐帧驱动：
    # waiting→airborne→second_capture→complete。返回 True 表示本帧发生状态转移。
    if bounce['phase'] == 'second_capture':
        clean_g = sanitize_g(sample.g_force)
        if clean_g is not None:
            if bounce['second_peak_g'] is None or clean_g > bounce['second_peak_g']:
                bounce['second_peak_g'] = clean_g
        if sample.t >= bounce['second_capture_until']:
            bounce['phase'] = 'complete'
            bounce['second_g_ready'] = True
            return True
        return False

    if bounce['phase'] == 'complete':
        return False
    if sample.t > bounce['monitor_until']:
        bounce['phase'] = 'complete'
        return True

    if bounce['phase'] == 'waiting':
        if not sample.on_ground and bounce['prev_on_ground']:
            bounce['phase'] = 'airborne'
            bounce['airborne_start'] = sample.t
            bounce['peak_agl'] = max(0.0, sample.agl_ft or 0.0)
            bounce['peak_upward'] = max(0.0, sample.local_vy_mps or 0.0)
            bounce['prev_on_ground'] = sample.on_ground
            return True
    elif bounce['phase'] == 'airborne':
        if not sample.on_ground:
            bounce['peak_agl'] = max(bounce['peak_agl'], sample.agl_ft or 0.0)
            bounce['peak_upward'] = max(bounce['peak_upward'], sample.local_vy_mps or 0.0)
        elif not bounce['prev_on_ground']:
            duration = max(0.0, sample.t - bounce['airborne_start'])
            valid = (
                duration >= BOUNCE_MIN_AIRBORNE_SECONDS
                and (
                    bounce['peak_agl'] >= BOUNCE_MIN_PEAK_AGL_FT
                    or bounce['peak_upward'] >= BOUNCE_MIN_UPWARD_MPS
                )
            )
            if valid:
                bounce['detected'] = True
                bounce['second_touch_time'] = sample.t
                bounce['second_capture_until'] = sample.t + BOUNCE_SECOND_G_CAPTURE_SECONDS
                touch_g = sanitize_g(sample.g_force) or 1.0
                bounce['second_touch_g'] = touch_g
                bounce['second_peak_g'] = touch_g
                bounce['second_curve_g'] = touch_g
                bounce['phase'] = 'second_capture'
            else:
                bounce['phase'] = 'waiting'
                bounce['airborne_start'] = 0.0
                bounce['peak_agl'] = 0.0
                bounce['peak_upward'] = 0.0
            bounce['prev_on_ground'] = sample.on_ground
            return True
    bounce['prev_on_ground'] = sample.on_ground
    return False


def analyze_landing(samples, touchdown_sample):
    touch_time = touchdown_sample.t
    pre_touch_time = touch_time - PRE_TOUCH_BUFFER_SECONDS
    pre_touch_samples = [s for s in samples if s.t <= touch_time and s.t >= pre_touch_time]

    # MSFS 数据源修正：RADIO HEIGHT 在接地前存在约 +12.7 ft 的固定偏高
    # （RA_BIAS_OFFSET_FT，视频逐帧比对确认）。接地确认后把接地前所有
    # 离地样本的 RA 统一减去该偏移（不低于 0）再分析；接地后样本保持原值，
    # 使 0.5 秒聚合轨迹表的 RA 与 AGL 几何链使用修正后的高度。
    corrected_samples = [
        s._replace(agl_ft=max(0.0, s.agl_ft - RA_BIAS_OFFSET_FT))
        if (s.t < touch_time and not s.on_ground and s.agl_ft is not None)
        else s
        for s in samples
    ]

    raw_touchdown_fpm = (
        pre_touch_samples[0].fpm
        if len(pre_touch_samples) < 5
        else pre_touch_samples[-5].fpm
    )

    # ---- 三链 FPM 验证（完整复现 Lua 版 v1.1 analyze_landing_velocity）----
    # 三条独立测量链：物理速度 P25（250ms 终端窗）、同窗 VVI 中位数、AGL 几何斜率。
    vvi_fpm, vvi_min_fpm, vvi_sample_count, vvi_valid = compute_vvi_metrics(samples, touch_time, raw_touchdown_fpm)
    physical_fpm, physical_sample_count, physical_valid = compute_physical_fpm(samples, touch_time)
    physical_short_fpm = compute_short_physical_median(samples, touch_time - PHYSICAL_FPM_SHORT_WINDOW_SECONDS, touch_time)
    agl_fpm, agl_sample_count, agl_sample_span, agl_pair_count = compute_agl_closure_fpm(corrected_samples, touch_time)
    agl_valid = agl_fpm is not None

    fpm_difference = (physical_fpm - vvi_fpm) if physical_fpm is not None and vvi_fpm is not None else 0

    if physical_valid and vvi_valid and agl_valid:
        agl_physical_difference = physical_fpm - agl_fpm
        agl_vvi_difference = vvi_fpm - agl_fpm
        fpm_max_pair_difference = max(
            abs(fpm_difference),
            abs(agl_physical_difference),
            abs(agl_vvi_difference),
        )

        if fpm_max_pair_difference <= MAX_PAIR_DIFFERENCE_FPM:
            confidence = "HIGH"
            fpm_method = "PHYSICAL"
            fpm_method_detail = "三项终端测量结果一致，采用物理轨迹下降率"
            flare_fpm_source = "PHYSICAL"
            selected_fpm = round_num(physical_fpm)
        elif abs(agl_vvi_difference) <= MAX_PAIR_DIFFERENCE_FPM:
            confidence = "MEDIUM"
            fpm_method = "VVI"
            fpm_method_detail = "终端测量出现差异，VVI与几何轨迹相互接近，采用VVI下降率"
            flare_fpm_source = "VVI"
            selected_fpm = round_num(vvi_fpm)
        else:
            confidence = "LOW"
            fpm_method = "VVI"
            fpm_method_detail = "终端测量结果分散，采用VVI下降率并保留全部对照值"
            flare_fpm_source = "VVI"
            selected_fpm = round_num(vvi_fpm)
    else:
        agl_physical_difference = 0
        agl_vvi_difference = 0
        fpm_max_pair_difference = 0
        confidence = "LOW"
        fpm_method = "VVI"
        flare_fpm_source = "VVI"
        if vvi_fpm is not None:
            fpm_method_detail = "终端测量样本不足，采用VVI下降率并保留全部对照值"
            selected_fpm = round_num(vvi_fpm)
        else:
            # 无有效 VVI 时回退到触地前快照（对应 Lua 的 approach_data.vs_fpm 回退）。
            fpm_method_detail = "终端测量样本不足且无有效VVI，采用触地前快照"
            selected_fpm = raw_touchdown_fpm
            # 诊断输出：打印各链样本数与触地前最后一小段原始样本，
            # 便于确认触地前终端窗口是否仍有采样断档。
            print(f"[诊断] 终端窗口样本不足: 物理={physical_sample_count} VVI={vvi_sample_count} AGL={agl_sample_count}")
            for s in sorted((x for x in samples if touch_time - 0.30 <= x.t <= touch_time), key=lambda x: x.t):
                fpm = f"{s.fpm:.0f}" if s.fpm is not None else "None"
                vy = f"{s.local_vy_mps:.3f}" if s.local_vy_mps is not None else "None"
                agl = f"{s.agl_ft:.2f}" if s.agl_ft is not None else "None"
                print(f"    t={s.t - touch_time:+.3f}s onG={int(s.on_ground)} fpm={fpm} vy={vy} agl={agl}")

    # ---- G 过载分析（完整复现 Lua 版 v1.1 analyze_landing_impulse）----
    # 垂直投影 G、冲量一致性误差、HIGH/MEDIUM/LOW 置信度与备用 G 上限。
    g_result = analyze_landing_g(
        samples,
        touch_time,
        touchdown_sample,
        selected_fpm,
        physical_valid,
        physical_fpm,
        vvi_fpm,
    )
    landing_g = g_result['landing_g']

    heading = touchdown_sample.heading_deg
    runway = estimated_runway_from_heading(heading)

    # ---- 拉平曲线（完整复现 Lua 版 v1.1 update_flare_trace + analyze_flare_curve）----
    # 使用修正 RA 后的样本重建轨迹：轨迹在修正后 100 ft 处启动（原始 RA ~112.7 ft），
    # 既修正了轨迹表 RA 数值，又自动向前多缓存约 1.2 s 进近数据，首行仍约 100 ft。
    flare_trace_result = reconstruct_flare_trace(corrected_samples, touch_time)
    flare_start_time = flare_trace_result['start_time']
    # 与 Lua 版一致：拉平曲线下降率取值由三链验证结果决定（PHYSICAL / VVI）。
    selected_fpm_source = lambda s: (s.local_vy_mps * 196.850394) if flare_fpm_source == "PHYSICAL" else (s.fpm or 0.0)
    flare_buckets, flare_bucket_limited, flare_raw_count = build_flare_buckets(
        flare_trace_result['samples'],
        flare_start_time,
        touch_time,
        selected_fpm_source,
        selected_fpm,
        touchdown_sample,
        physical_fpm,
        vvi_fpm,
        physical_valid,
    )
    flare_limited = flare_trace_result['limited'] or flare_bucket_limited
    flare_analysis = analyze_flare_curve(flare_buckets, flare_start_time, touch_time, flare_raw_count)
    flare_valid = flare_analysis['valid']

    landing_status = classify_landing(selected_fpm, landing_g)

    # ---- 弹跳检测与第二次触地分析（完整复现 Lua 版 v1.1 弹跳模块）----
    # 任一离地样本进入离地阶段；第二次接地时按持续离地时间与峰值条件判定弹跳；
    # 第二次压缩 0.35 s 窗口的 P75 投影 G 作为 second_curve_g，并执行评分降级。
    bounce_result = analyze_bounce_in_samples(samples, touch_time)
    bounce_result['original_status'] = status_short(landing_status)
    new_status, bounce_applied = apply_bounce_score(landing_status, bounce_result, landing_g)
    if bounce_applied:
        bounce_result['score_applied'] = True
        landing_status = new_status
    else:
        bounce_result['score_applied'] = False

    return {
        'touch_time': touch_time,
        'landing_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'landing_fpm': selected_fpm,
        'landing_ias_kts': touchdown_sample.ias_kts,
        'landing_tas_kts': touchdown_sample.tas_kts,
        'landing_gs_kts': touchdown_sample.groundspeed_kts,
        'landing_aoa_deg': touchdown_sample.aoa_deg,
        'landing_pitch_deg': touchdown_sample.pitch_deg,
        'landing_roll_deg': touchdown_sample.roll_deg,
        'landing_wind_speed_kts': touchdown_sample.wind_speed_kts,
        'landing_wind_heading_deg': touchdown_sample.wind_heading_deg,
        'landing_heading_deg': heading,
        'landing_status': landing_status,
        'landing_g': g_result['landing_g'],
        'landing_touch_g': g_result['landing_touch_g'],
        'landing_peak_g': g_result['landing_peak_g'],
        'landing_curve_g': g_result['landing_curve_g'],
        'landing_baseline_g': g_result['landing_baseline_g'],
        'landing_local_event_g': g_result['landing_local_event_g'],
        'landing_local_event_g_valid': g_result['landing_local_event_g_valid'],
        'landing_robust_g': g_result['landing_robust_g'],
        'landing_equivalent_g': g_result['landing_equivalent_g'],
        'landing_impulse_delta_mps': g_result['landing_impulse_delta_mps'],
        'landing_velocity_delta_mps': g_result['landing_velocity_delta_mps'],
        'landing_high_g_duration_seconds': g_result['landing_high_g_duration_seconds'],
        'landing_max_sample_gap_seconds': g_result['landing_max_sample_gap_seconds'],
        'landing_average_sample_gap_seconds': g_result['landing_average_sample_gap_seconds'],
        'landing_consistency_error': g_result['landing_consistency_error'],
        'landing_g_confidence': g_result['landing_g_confidence'],
        'landing_g_method': g_result['landing_g_method'],
        'landing_used_fallback': g_result['landing_used_fallback'],
        'landing_impact_sample_count': g_result['landing_impact_sample_count'],
        'landing_capture_end_reason': g_result['landing_capture_end_reason'],
        'landing_stop_duration_seconds': g_result['landing_stop_duration_seconds'],
        'landing_physical_fpm': physical_fpm,
        'landing_physical_short_fpm': physical_short_fpm,
        'landing_vvi_fpm': vvi_fpm,
        'landing_vvi_min_fpm': vvi_min_fpm,
        'landing_agl_fpm': agl_fpm,
        'landing_fpm_method': fpm_method,
        'landing_fpm_method_detail': fpm_method_detail,
        'landing_fpm_confidence': confidence,
        'landing_flare_fpm_source': flare_fpm_source,
        'landing_fpm_difference': fpm_difference,
        'landing_agl_physical_difference': agl_physical_difference,
        'landing_agl_vvi_difference': agl_vvi_difference,
        'landing_fpm_max_pair_difference': fpm_max_pair_difference,
        'landing_physical_sample_count': physical_sample_count,
        'landing_vvi_sample_count': vvi_sample_count,
        'landing_agl_sample_count': agl_sample_count,
        'landing_agl_pair_count': agl_pair_count,
        'landing_agl_sample_span_seconds': agl_sample_span,
        'landing_curve_analysis': flare_analysis,
        'flare_buckets': flare_buckets,
        'flare_valid': flare_valid,
        'flare_raw_sample_count': flare_raw_count,
        'flare_limited': flare_limited,
        'flare_bucket_count': len(flare_buckets),
        'bounce_result': bounce_result,
        'landing_context': {
            'airport_id': 'UNKNOWN',
            'airport_name': '',
            'runway': runway,
            'airport_distance_km': 0.0,
            'aircraft_icao': 'UNKNOWN',
            'aircraft_file': '',
            'touch_latitude': 0.0,
            'touch_longitude': 0.0,
        },
        'landing_surface': {
            'warning_text': '未检测到持续降雨或湿滑道面',
            'precipitation_ratio': 0.0,
            'consecutive_rain_samples': 0,
            'runway_friction': 0.0,
            'source_text': '未检测',
        },
        'settings': {
            'display_seconds': 30,
            'popup_position': 'middle_left',
            'popup_layout': 'horizontal',
            'panel_opacity_level': 25,
            'show_math_log': False,
        },
    }


def write_landing_report(report):
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f"Starlux_Report_{timestamp}.txt"
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    filepath = os.path.join(desktop, filename)
    try:
        os.makedirs(desktop, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\ufeff')
            f.write('StarLux 落地率插件 MSFS 记录\n')
            f.write('======================================================================\n\n')
            f.write('一、核心落地结果\n')
            f.write('----------------------------------------------------------------------\n')
            f.write(f"落地时间（本地时间）: {report['landing_timestamp']}\n")
            f.write(f"最终评价: {status_short(report['landing_status'])}\n")
            f.write(f"评价说明: {status_explanation(report['landing_status'], report['bounce_result'])}\n")
            f.write(f"触地垂直速度: {vertical_speed_log_text(report['landing_fpm'])}\n")
            f.write(f"下降率取值: {'物理轨迹（三项终端测量一致）' if report['landing_fpm_method'] == 'PHYSICAL' else '垂直速度 VVI（终端链路差异时自动采用）'}\n")
            f.write(f"FPM数据可信度: {report['landing_fpm_confidence']}\n")
            f.write(f"最终过载: {report['landing_g']:.2f} G\n")
            if report['flare_valid']:
                f.write(f"拉平曲率: {report['landing_curve_analysis']['metric']:.1f} fpm/s²（|二阶变化|第75百分位，越接近0表示轨迹越平顺）\n")
            else:
                f.write(f"拉平曲率: 无有效结果（{report['landing_curve_analysis']['trend_text']}）\n")
            f.write(f"拉平轨迹结论: {report['landing_curve_analysis']['trend_text']}\n")
            f.write(f"弹跳检测: {'发生弹跳' if report['bounce_result']['detected'] else '未检测到弹跳'}\n")
            f.write(f"机型（ICAO）: {report['landing_context']['aircraft_icao']}\n")
            if report['landing_context']['airport_id'] == 'UNKNOWN':
                f.write('落地机场: 未能识别\n')
            else:
                f.write(f"落地机场: {report['landing_context']['airport_id']} - {report['landing_context']['airport_name']}\n")
            f.write(f"触地跑道方向: RWY{report['landing_context']['runway']}（推算）\n")
            f.write(f"IAS / GS: {report['landing_ias_kts']:.0f} / {report['landing_gs_kts']:.0f} kt\n")
            f.write(f"相对风: {build_wind_relative_text(report['landing_wind_heading_deg'], report['landing_wind_speed_kts'], report['landing_heading_deg'])}\n")
            f.write(f"道面提示: {report['landing_surface']['warning_text']}\n\n")

            if report['bounce_result']['detected']:
                bounce = report['bounce_result']
                f.write('弹跳与两次触地\n')
                f.write('----------------------------------------------------------------------\n')
                f.write(f"第一次触地: {format_fpm(report['landing_fpm'])} / {report['landing_g']:.2f} G\n")
                f.write(f"第二次触地: {format_fpm(bounce['second_fpm'])} / {(bounce['second_curve_g'] or 1.0):.2f} G（触地帧 {(bounce['second_touch_g'] or 0):.2f} G，原始峰值 {(bounce['second_peak_g'] or 0):.2f} G）\n")
                f.write(f"两次触地间隔: {bounce['second_touch_time'] - bounce['first_touch_time']:.2f} s\n")
                f.write(f"确认离地时间: {bounce['airborne_duration_seconds']:.2f} s\n")
                f.write(f"弹跳期间峰值无线电高度: {bounce['airborne_peak_agl_ft']:.2f} ft\n")
                f.write(f"弹跳期间最大向上速度: {bounce['airborne_peak_upward_mps']:.3f} m/s\n")
                f.write(f"弹跳前评价: {status_full_text(bounce.get('original_status') or report['landing_status'])}\n")
                f.write(f"弹跳后评价: {status_full_text(report['landing_status'])}\n")
                f.write('规则: Nice 降为 Stable，Stable 降为 Attention；任一次稳健 G 超过 1.80 时为 UNSTABLE。\n\n')

            f.write('二、100英尺后拉平轨迹\n')
            f.write('----------------------------------------------------------------------\n')
            f.write(f"原始采样频率: {1 / FLARE_SAMPLE_INTERVAL_SECONDS:.1f} Hz\n")
            f.write(f"原始样本数: {report['flare_raw_sample_count']}\n")
            f.write(f"0.5秒聚合点数: {report['flare_bucket_count']}\n")
            f.write(f"是否达到容量上限: {'是' if report['flare_limited'] else '否'}\n")
            f.write(f"100 ft 至触地时间: {report['landing_curve_analysis']['duration_seconds']:.2f} s\n")
            f.write(f"轨迹下降率取值: {'物理轨迹（三项终端测量一致）' if report['landing_fpm_method'] == 'PHYSICAL' else '垂直速度 VVI（终端链路差异时自动采用）'}\n")
            f.write(f"100 ft 附近下降率: {format_fpm(report['landing_curve_analysis']['entry_fpm'])}\n")
            f.write(f"触地下降率: {format_fpm(report['landing_fpm'])}\n")
            f.write(f"下降率净改善量: {report['landing_curve_analysis']['recovery_fpm']:+.0f} fpm\n")
            f.write(f"拉平曲率: {report['landing_curve_analysis']['metric']:.1f} fpm/s²\n")
            f.write(f"有符号平均曲率: {report['landing_curve_analysis']['signed_mean_curvature']:+.1f} fpm/s²\n")
            f.write(f"明显方向反转次数: {report['landing_curve_analysis']['reversal_count']}\n")
            f.write(f"下降率恶化区间比例: {report['landing_curve_analysis']['worsening_ratio'] * 100:.1f}%\n")
            f.write(f"单调改善效率: {report['landing_curve_analysis']['monotonic_efficiency'] * 100:.1f}%\n")
            f.write(f"末段改善占比: {report['landing_curve_analysis']['late_recovery_ratio'] * 100:.1f}%\n")
            f.write(f"轨迹结论: {report['landing_curve_analysis']['trend_text']}\n")
            f.write(f"明显反转门槛: 相邻聚合FPM变化绝对值超过 {FLARE_REVERSAL_NOISE_FPM:.0f} fpm\n")
            f.write(f"高震荡规则: 反转次数 >= {FLARE_OSCILLATION_SEVERE_REVERSAL_MIN}，或反转次数 >= {FLARE_OSCILLATION_HIGH_REVERSAL_MIN} 且（单调改善效率 < {FLARE_OSCILLATION_EFFICIENCY_MAX:.2f} 或恶化区间比例 >= {FLARE_OSCILLATION_WORSENING_RATIO_MIN:.2f}）。\n")
            f.write('评分说明: 拉平曲率仅用于复盘，不参与最终评分。\n')
            f.write(f"曲率分析耗时: {report['landing_curve_analysis']['calculation_ms']:.3f} ms\n\n")

            if report['flare_buckets']:
                f.write('0.5秒聚合轨迹表\n')
                f.write('----------------------------------------------------------------------\n')
                f.write('T+秒       RA(ft)   轨迹FPM   VVI   IAS   GS   Pitch   AoA   Roll   物理FPM\n')
                f.write('--------------------------------------------------------------------------------\n')
                base_t = report['flare_buckets'][0]['t']
                for bucket in report['flare_buckets']:
                    rel_sec = bucket['t'] - base_t
                    f.write(
                        f"{rel_sec:9.3f}  {bucket['agl_ft']:8.2f}  {bucket['selected_fpm']:8.0f}  {bucket['vvi_fpm'] if bucket['vvi_fpm'] is not None else 0:5.0f}  {bucket['ias_kts']:5.0f}  {bucket['gs_kts']:5.0f}  {bucket['pitch_deg']:+6.1f}  {bucket['aoa_deg']:+5.1f}  {bucket['roll_deg']:+5.1f}  {bucket['physical_fpm']:8.0f}\n"
                    )
                f.write('\n')
            else:
                f.write('0.5秒聚合轨迹表: 无有效轨迹数据\n\n')

            f.write('三、飞行、位置与环境参考\n')
            f.write('----------------------------------------------------------------------\n')
            f.write(f"触地点距机场参考点: {report['landing_context']['airport_distance_km']:.1f} km\n")
            f.write('跑道说明: 根据触地磁航向推算，暂不区分 L/R/C。\n')
            f.write(f"真空速（TAS）: {report['landing_tas_kts']:.0f} kt\n")
            f.write(f"迎角: {report['landing_aoa_deg']:.1f} deg\n")
            f.write(f"横滚角: {roll_log_text(report['landing_roll_deg'])}\n")
            f.write(f"飞机磁航向: {report['landing_heading_deg']:.0f} deg\n")
            f.write(f"风向和风速: 来自 {round_num(normalize_deg(report['landing_wind_heading_deg'])):03d}deg， {round_num(report['landing_wind_speed_kts'])}kt\n")
            f.write('触地前三分钟实际降水峰值: 0.0%\n')
            f.write('连续达到降水阈值的采样数: 0\n')
            f.write('跑道摩擦状态: 未获取\n')
            f.write('道面判定来源: 未检测\n\n')

            f.write('四、FPM与G算法诊断\n')
            f.write('----------------------------------------------------------------------\n')
            f.write(f"最终显示/评分 FPM: {format_fpm(report['landing_fpm'])}\n")
            f.write(f"FPM数据可信度: {report['landing_fpm_confidence']}\n")
            f.write(f"下降率取值说明: {report.get('landing_fpm_method_detail', report['landing_fpm_method'])}\n")
            f.write(f"三链终端窗口: 触地前 {PHYSICAL_FPM_WINDOW_SECONDS * 1000:.0f} ms、AGL不高于 {FLARE_START_AGL_FT} ft\n")
            f.write(f"同窗 VVI 中位数: {format_fpm(report['landing_vvi_fpm'])}\n")
            if report['landing_physical_fpm'] is not None:
                f.write(f"250 ms 物理速度第25百分位: {format_fpm(report['landing_physical_fpm'])}\n")
            else:
                f.write('250 ms 物理速度第25百分位: 样本不足\n')
            f.write(f"80 ms 物理速度中位数: {format_fpm(report['landing_physical_short_fpm'])}\n")
            f.write(f"0.85 s 最差 VVI: {format_fpm(report['landing_vvi_min_fpm'])}\n")
            if report['landing_agl_fpm'] is not None:
                f.write(f"第三链 AGL 高度变化下降率: {format_fpm(report['landing_agl_fpm'])}\n")
            else:
                f.write('第三链 AGL 高度变化下降率: 样本不足，无法确认\n')
            f.write(f"物理主值与同窗 VVI 差值: {report['landing_fpm_difference']:+.0f} fpm\n")
            f.write(f"物理FPM与AGL链差值: {report['landing_agl_physical_difference']:+.0f} fpm\n")
            f.write(f"VVI与AGL链差值: {report['landing_agl_vvi_difference']:+.0f} fpm\n")
            f.write(f"三链最大两两差值: {report['landing_fpm_max_pair_difference']} fpm\n")
            f.write(f"FPM物理/VVI窗口样本数: {report['landing_physical_sample_count']} / {report['landing_vvi_sample_count']}\n")
            f.write(f"AGL验证样本/跨度: {report['landing_agl_sample_count']} / {report['landing_agl_sample_span_seconds']:.3f} s\n")
            f.write(f"触地帧过载: {report['landing_touch_g']:.2f} G\n")
            f.write(f"第一次压缩原始峰值: {report['landing_peak_g']:.2f} G\n")
            f.write(f"第75百分位曲线 G: {report['landing_curve_g']:.2f} G\n")
            if report['landing_local_event_g_valid']:
                f.write(f"160 ms 局部冲击包络 G: {report['landing_local_event_g']:.2f} G\n")
            else:
                f.write('160 ms 局部冲击包络 G: 样本不足，使用全局P75\n')
            f.write(f"中可信度稳健冲击 G: {report['landing_robust_g']:.2f} G\n")
            f.write(f"接地前垂直 G 基线: {report['landing_baseline_g']:.2f} G\n")
            f.write(f"冲量等效 G: {report['landing_equivalent_g']:.2f} G\n")
            f.write(f"第一次压缩结束原因: {report['landing_capture_end_reason']}\n")
            f.write(f"第一次压缩持续时间: {report['landing_stop_duration_seconds'] * 1000:.0f} ms\n")
            f.write(f"高 G 时长: {report['landing_high_g_duration_seconds'] * 1000:.0f} ms\n")
            f.write(f"G 冲量推算速度变化: {report['landing_impulse_delta_mps']:.3f} m/s\n")
            f.write(f"实际垂直速度变化: {report['landing_velocity_delta_mps']:.3f} m/s\n")
            f.write(f"冲量一致性误差: {report['landing_consistency_error'] * 100:.1f}%\n")
            f.write(f"数据可信度: {confidence_level_text(report['landing_g_confidence'])}\n")
            f.write(f"最终 G 采用方式: {report['landing_g_method']}\n")
            f.write(f"是否启用备用算法: {'是' if report['landing_used_fallback'] else '否'}\n")
            f.write(f"冲击阶段有效样本数: {report['landing_impact_sample_count']}\n")
            f.write(f"冲击样本平均间隔: {report['landing_average_sample_gap_seconds'] * 1000:.1f} ms\n")
            f.write(f"冲击样本最大间隔: {report['landing_max_sample_gap_seconds'] * 1000:.1f} ms\n")
            f.write('冲量计算和详细数学复盘已启用\n')
            f.write('完整脚本已实现三链FPM验证、AGL回归、物理下降率和 G 过载分析。\n\n')

            f.write('五、评分阈值与显示设置\n')
            f.write('----------------------------------------------------------------------\n')
            f.write(f"Nice: FPM ≤ {FPM_NICE_MAX}，G ≤ {G_NICE_MAX:.2f}\n")
            f.write(f"Stable: FPM ≤ {FPM_STABLE_MAX}，G ≤ {G_STABLE_MAX:.2f}\n")
            f.write(f"Attention: FPM ≤ {FPM_ATTENTION_MAX}，G ≤ {G_ATTENTION_MAX:.2f}\n")
            f.write('UNSTABLE: FPM 或 G 超过任意 Attention 上限。\n')
            f.write('FPM 与 G 分别分档，最终评价取较严重等级。\n')
            f.write('完整数学复算附录: 关闭\n')
    except Exception as e:
        print(f"[错误] 写入报告失败: {e}")
        return None
    return filepath


def query_value(aq, name):
    try:
        value = aq.get(name)
    except Exception:
        return None
    return safe_float(value)


# =========================
# 批量数据读取（MSFS 高频采样）
# =========================
# 库默认的 AircraftRequests.get() 每次都要发一次性请求并 sleep(0.01) 轮询等待
# 后台分发线程回填（get_data 内部），13 个变量一帧累计约 200 ms，
# 导致实际采样率只有约 4 Hz，远低于 25 Hz 目标。
# 这里把所有变量放进同一条数据定义，每帧只发一次请求、一次往返拿回全部数值。
_BATCH_SIMVARS = [
    (b'SIM ON GROUND', b'Bool'),
    (b'VERTICAL SPEED', b'feet/minute'),
    (b'G FORCE', b'GForce'),
    (b'RADIO HEIGHT', b'Feet'),
    (b'PLANE ALT ABOVE GROUND', b'Feet'),
    (b'PLANE ALTITUDE', b'Feet'),
    (b'GROUND ALTITUDE', b'Meters'),
    (b'VELOCITY WORLD Y', b'Feet per second'),
    (b'AIRSPEED INDICATED', b'Knots'),
    (b'AIRSPEED TRUE', b'Knots'),
    (b'PLANE PITCH DEGREES', b'Radians'),
    (b'PLANE BANK DEGREES', b'Radians'),
    (b'PLANE HEADING DEGREES MAGNETIC', b'Radians'),
    (b'HEADING INDICATOR', b'Radians'),
    (b'INCIDENCE ALPHA', b'Radians'),
    (b'GROUND VELOCITY', b'Knots'),
    (b'GPS GROUND SPEED', b'Meters per second'),
    (b'GPS GROUND MAGNETIC TRACK', b'Radians'),
    (b'GPS GROUND TRUE TRACK', b'Radians'),
    (b'MAGVAR', b'Degrees'),
]
_BATCH_KEYS = [
    'SIM_ON_GROUND', 'VERTICAL_SPEED', 'G_FORCE', 'RADIO_HEIGHT',
    'PLANE_ALT_ABOVE_GROUND', 'PLANE_ALTITUDE', 'GROUND_ALTITUDE',
    'VELOCITY_WORLD_Y', 'AIRSPEED_INDICATED', 'AIRSPEED_TRUE',
    'PLANE_PITCH_DEGREES', 'PLANE_BANK_DEGREES', 'PLANE_HEADING_DEGREES_MAGNETIC',
    'HEADING_INDICATOR', 'INCIDENCE_ALPHA', 'GROUND_VELOCITY',
    'GPS_GROUND_SPEED', 'GPS_GROUND_MAGNETIC_TRACK', 'GPS_GROUND_TRUE_TRACK',
    'MAGVAR',
]


class BatchSimConnect(SimConnect):
    """一次往返读取全部 simvar 的高频数据连接。

    继承库的 SimConnect：把全部变量定义到一条数据定义里，并覆盖
    handle_simobject_event 把整包数值写入列表；read_all() 发一次请求后
    等待后台分发线程回填（与库 get_data 相同的轮询方式，但只有一次往返）。
    """

    def __init__(self, simvar_specs):
        self._specs = list(simvar_specs)
        self._values = [None] * len(self._specs)
        self._fresh = False
        super().__init__()
        self._batch_def = self.new_def_id()
        self._batch_req = self.new_request_id()
        for name, unit in self._specs:
            err = self.dll.AddToDataDefinition(
                self.hSimConnect,
                self._batch_def.value,
                name, unit,
                SIMCONNECT_DATATYPE.SIMCONNECT_DATATYPE_FLOAT64,
                0, SIMCONNECT_UNUSED,
            )
            if not self.IsHR(err, 0):
                raise RuntimeError('AddToDataDefinition 失败: %s %s' % (name, unit))

    def handle_simobject_event(self, ObjData):
        if ObjData.dwRequestID == self._batch_req.value:
            n = len(self._specs)
            arr = cast(ObjData.dwData, POINTER(c_double * n)).contents
            for i in range(n):
                self._values[i] = arr[i]
            self._fresh = True
            return
        super().handle_simobject_event(ObjData)

    def read_all(self):
        """发送一次批量请求并等待最新一帧数据返回（最多约 200 ms）。"""
        self._fresh = False
        self.dll.RequestDataOnSimObjectType(
            self.hSimConnect,
            self._batch_req.value,
            self._batch_def.value,
            0,
            SIMCONNECT_SIMOBJECT_TYPE.SIMCONNECT_SIMOBJECT_TYPE_USER,
        )
        attempts = 0
        while not self._fresh and attempts < 100:
            time.sleep(0.002)
            attempts += 1
        return list(self._values)


class _DictReader:
    """把批量读取结果包成 aq.get(name) 接口，build_sample 无需改动。"""

    def __init__(self, mapping):
        self._m = mapping

    def get(self, name):
        return self._m.get(name)


def build_sample(aq, now):
    on_ground = bool(query_value(aq, 'SIM_ON_GROUND') or 0)
    fpm = query_value(aq, 'VERTICAL_SPEED')
    g_force = query_value(aq, 'G_FORCE')
    ias = query_value(aq, 'AIRSPEED_INDICATED')
    tas = query_value(aq, 'AIRSPEED_TRUE') or ias
    pitch = query_value(aq, 'PLANE_PITCH_DEGREES')
    roll = query_value(aq, 'PLANE_BANK_DEGREES')
    heading = query_value(aq, 'PLANE_HEADING_DEGREES_MAGNETIC') or query_value(aq, 'HEADING_INDICATOR')
    aoa = query_value(aq, 'INCIDENCE_ALPHA')
    # RADIO_HEIGHT（真实无线电高度）优先：接地时正确归零，
    # 不会被 PLANE_ALTITUDE-GROUND_ALTITUDE 的地形滞后值抬高（触地时仍读十余英尺）。
    agl = query_value(aq, 'RADIO_HEIGHT')
    if agl is None:
        agl = query_value(aq, 'PLANE_ALT_ABOVE_GROUND')
    if agl is None:
        plane_alt = query_value(aq, 'PLANE_ALTITUDE')
        ground_alt = query_value(aq, 'GROUND_ALTITUDE')
        if plane_alt is not None and ground_alt is not None:
            agl = plane_alt - ground_alt
    gkts = query_value(aq, 'GROUND_VELOCITY')
    # 世界系垂直速度（与 X-Plane local_vy 语义一致）优先；不可用时用指示垂直速度换算。
    # 不使用 VELOCITY_BODY_Y：机身轴系速度在本环境下与真实下降率严重不符（约高 7~8 倍）。
    local_vy_fps = query_value(aq, 'VELOCITY_WORLD_Y')
    if local_vy_fps is not None:
        local_vy_mps = local_vy_fps * 0.3048
    elif fpm is not None:
        local_vy_mps = fpm / 196.850394
    else:
        local_vy_mps = None
    if gkts is None:
        gkts = 0.0
    if pitch is not None:
        pitch = pitch * RAD_TO_DEG
    else:
        pitch = 0.0
    if roll is not None:
        # 本环境下 PLANE_BANK_DEGREES 的符号与真实横滚方向相反（实测左倾却显示右倾），
        # 取反后统一约定：正值=右倾（右翼下沉）、负值=左倾（左翼下沉）。
        roll = -roll * RAD_TO_DEG
    else:
        roll = 0.0
    if heading is not None:
        heading = heading * RAD_TO_DEG
    else:
        heading = 0.0
    if aoa is not None:
        aoa = aoa * RAD_TO_DEG
    else:
        aoa = 0.0

    wind_speed_kts, wind_heading_deg = compute_wind_from_gps(aq, heading, tas or 0.0, now)

    return Sample(
        t=now,
        on_ground=on_ground,
        fpm=fpm,
        local_vy_mps=local_vy_mps,
        agl_ft=agl,
        g_force=g_force,
        ias_kts=ias or 0.0,
        tas_kts=tas or 0.0,
        pitch_deg=pitch,
        roll_deg=roll,
        heading_deg=heading,
        groundspeed_kts=gkts or 0.0,
        aoa_deg=aoa,
        wind_speed_kts=wind_speed_kts,
        wind_heading_deg=wind_heading_deg,
    )


def main():
    print('正在连接到模拟飞行 (MSFS)...')
    sm = None
    while True:
        try:
            sm = BatchSimConnect(_BATCH_SIMVARS)
            print('连接成功！正在抓取实时数据...\n')
            break
        except KeyboardInterrupt:
            print('\n\n程序已手动终止。')
            return
        except Exception as e:
            print(f'连接失败，模拟飞行可能尚未启动。2 秒后重试。错误信息: {e}')
            time.sleep(2.0)

    state_samples = deque(maxlen=RING_BUFFER_SIZE)
    was_on_ground = True
    landing_history = []
    landing_active = None
    # 单帧读取失败时用于补齐的上一帧有效值。
    last_fpm = None
    last_local_vy = None
    last_g = None
    last_agl = None
    last_valid_time = None
    frame_count = 0
    print('准备监听落地事件...')

    try:
        while True:
            now = time.monotonic()
            frame_count += 1
            # 每帧一次批量往返读取全部 simvar（替代逐项 aq.get() 的多次往返，
            # 这是采样率从 ~4 Hz 恢复到 16 Hz 目标的关键）。
            values = sm.read_all()
            aq = _DictReader(dict(zip(_BATCH_KEYS, values)))
            sample = build_sample(aq, now)

            # 先记录本帧的有效值，作为后续补齐的来源。
            if sample.fpm is not None:
                last_fpm = sample.fpm
            if sample.local_vy_mps is not None:
                last_local_vy = sample.local_vy_mps
            if sample.g_force is not None:
                last_g = sample.g_force
            if sample.agl_ft is not None:
                last_agl = sample.agl_ft
            if (sample.fpm is not None or sample.g_force is not None
                    or sample.local_vy_mps is not None or sample.agl_ft is not None):
                last_valid_time = now
            # 只有持续超过 1 秒完全没有有效数据（如 SimConnect 断开）才跳过；
            # 接地瞬间的短暂全 None 仍保留，由上一帧有效值补齐，避免断档。
            if last_valid_time is None or now - last_valid_time > 1.0:
                time.sleep(SAMPLE_INTERVAL_SECONDS)
                continue
            # 单帧读取失败不再整帧丢弃：补齐 fpm / local_vy / G / AGL，
            # 保留 on_ground 与有效字段，避免触地前采样断档导致终端窗口为空。
            if sample.fpm is None:
                sample = sample._replace(fpm=last_fpm)
            if sample.local_vy_mps is None:
                sample = sample._replace(local_vy_mps=last_local_vy)
            if sample.g_force is None:
                sample = sample._replace(g_force=last_g)
            if sample.agl_ft is None:
                sample = sample._replace(agl_ft=0.0 if sample.on_ground else last_agl)
            state_samples.append(sample)

            if not was_on_ground and sample.on_ground and landing_active is None:
                pre_touch = [s for s in state_samples if s.t < sample.t][-10:]
                if pre_touch:
                    touchdown_fpm = pre_touch[0].fpm if len(pre_touch) < 5 else pre_touch[-5].fpm
                else:
                    touchdown_fpm = sample.fpm
                landing_active = {
                    'start_time': now,
                    'touch_sample': sample,
                    'impact_timer': 0.0,
                    'max_g': sample.g_force,
                    'touchdown_fpm': touchdown_fpm,
                    'touchdown_pitch': sample.pitch_deg,
                    'touchdown_roll': sample.roll_deg,
                    'touchdown_ias': sample.ias_kts,
                    'bounce': {
                        'phase': 'waiting',
                        'monitor_until': now + BOUNCE_MONITOR_SECONDS,
                        'prev_on_ground': True,
                        'airborne_start': 0.0,
                        'peak_agl': 0.0,
                        'peak_upward': 0.0,
                        'detected': False,
                        'second_touch_time': None,
                        'second_capture_until': 0.0,
                        'second_touch_g': None,
                        'second_peak_g': None,
                        'second_curve_g': None,
                        'second_g_ready': False,
                    },
                }
                print('\n\n>>> 触发起落分析：主轮接地检测到！')

            if landing_active is not None:
                landing_active['impact_timer'] += SAMPLE_INTERVAL_SECONDS
                landing_active['max_g'] = max(landing_active['max_g'], sample.g_force)

                if not landing_active['touchdown_fpm'] and sample.fpm is not None:
                    landing_active['touchdown_fpm'] = sample.fpm

                # 弹跳监测状态机（复现 Lua process_bounce_monitor）。
                transitioned = update_live_bounce(landing_active['bounce'], sample)
                if transitioned:
                    bounce = landing_active['bounce']
                    if bounce['detected']:
                        print('\n>>> 检测到弹跳：已记录第二次触地数据。')
                    if bounce['second_g_ready']:
                        print(f"\n>>> 弹跳第二次触地分析完成：{bounce['second_curve_g']:.2f} G。")

                # 主分析在 1.20 s 冲击采集完成后执行；若弹跳正处于离地或
                # 第二次压缩采集阶段，则等待其结束再写报告，确保第二次触地
                # G 与评分降级数据完整（对应 Lua 延后写日志的设计意图）。
                if landing_active['impact_timer'] >= IMPACT_CAPTURE_MAX_SECONDS:
                    bounce = landing_active['bounce']
                    if bounce['phase'] not in ('airborne', 'second_capture'):
                        landing_samples = list(state_samples)
                        report = analyze_landing(landing_samples, landing_active['touch_sample'])
                        report_path = write_landing_report(report)
                        if report_path:
                            print(f'\n>>> 分析完成！报告已保存至: {report_path}')
                        else:
                            print('\n>>> 分析完成，但报告写入失败。')
                        landing_active = None
                        print('继续监听下一次起落 (拉起飞机即可)...\n')

            # 状态行每 5 帧刷新一次，降低 Windows 控制台 I/O 对采样率的拖累。
            if frame_count % 5 == 0:
                status_text = '地面' if sample.on_ground else '空中'
                print(f"\r飞行状态: {status_text} | 下降率: {sample.fpm if sample.fpm is not None else 0:5.0f} fpm | 实时G值: {sample.g_force if sample.g_force is not None else 0:4.2f} G | IAS: {sample.ias_kts:3.0f} kt   ", end='', flush=True)
            was_on_ground = sample.on_ground
            time.sleep(SAMPLE_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print('\n\n程序已手动终止。')
    except Exception as e:
        print(f'\n运行过程中出现意外错误: {e}')

if __name__ == '__main__':
    main()
