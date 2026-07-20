-- StarLux Landing Meter v0.6
-- For X-Plane 12 + FlyWithLua
-- v0.6 adds a dedicated settings window, persistent settings, and one TXT log per landing.

-- =========================
-- User Config
-- =========================

local POPUP_MODE = "touchdown"
-- "touchdown" = show shortly after touchdown
-- "taxi"      = show when ground speed drops below 30 kt

local DISPLAY_SECONDS = 30
-- Shorter G capture reduces post-touchdown gear compression / rolling oscillation influence.
local G_CAPTURE_SECONDS = 0.22
local TAXI_POPUP_SPEED_KT = 30

-- Compact popup position. The settings window exposes nine screen positions.
local POPUP_POSITION = "middle_left"
local PANEL_W = 340
local PANEL_H = 112
local PANEL_ALPHA = 0.58

local PATH_SEPARATOR = package.config:sub(1, 1)
local LMM_BASE_DIRECTORY = SCRIPT_DIRECTORY or "."

local function join_path(base, name)
    local last_char = base:sub(-1)
    if last_char == "/" or last_char == "\\" then
        return base .. name
    end
    return base .. PATH_SEPARATOR .. name
end

local SETTINGS_FILE_PATH = join_path(LMM_BASE_DIRECTORY, "LMM_Settings.cfg")
local LOG_DIRECTORY_PATH = join_path(LMM_BASE_DIRECTORY, "LMM_Log")

-- FPM capture logic.
-- "minimum_final" = use the strongest downward VS in the last short window before touchdown.
-- "last_frame"    = use the last airborne frame value.
local FPM_CAPTURE_MODE = "minimum_final"
local VS_SAMPLE_WINDOW_SECONDS = 0.85
local VS_SAMPLE_MAX_AGL_FT = 120

-- G scoring.
-- true  = use short-window peak G shortly after touchdown.
-- false = use touchdown-frame G only.
local USE_PEAK_G_FOR_SCORE = true

-- G robustness logic.
-- Raw peak G can spike after touchdown during gear compression, bounce, wheel spin-up,
-- or aggressive roll/pitch inputs. The displayed/scored G is therefore:
-- robust short-window G -> optionally capped by a simple FPM/G physics consistency guard.
local G_ROBUST_PERCENTILE = 0.85
local ENABLE_G_FPM_LOGIC_GUARD = true
local G_FPM_DECEL_TIME_SECONDS = 0.42
local G_LOGIC_MARGIN_SOFT = 0.10
local G_LOGIC_MARGIN_NORMAL = 0.14
local G_LOGIC_MARGIN_HARD = 0.20

-- Scoring thresholds
local FPM_STABLE_MAX = 220
local FPM_ATTENTION_MAX = 350

local G_STABLE_MAX = 1.30
local G_ATTENTION_MAX = 1.45

-- Optional external interface placeholder.
-- Keep nil for now. Later you can feed other computed quality indicators here.
-- Expected value: nil, "STABLE", "ATTENTION", or "UNSTABLE".
local EXTERNAL_SCORE_HINT = nil

-- Debug display. Can be toggled from the settings window.
local DEBUG_MODE = false

-- =========================
-- DataRefs
-- =========================

-- Core landing data
dataref("ma_vs_fpm", "sim/flightmodel/position/vh_ind_fpm", "readonly")
dataref("ma_y_agl_m", "sim/flightmodel/position/y_agl", "readonly")
dataref("ma_on_ground", "sim/flightmodel/failures/onground_any", "readonly")
dataref("ma_g_normal", "sim/flightmodel/forces/g_nrml", "readonly")
dataref("ma_roll_deg", "sim/flightmodel/position/phi", "readonly")
dataref("ma_groundspeed_mps", "sim/flightmodel/position/groundspeed", "readonly")
dataref("ma_running_time_sec", "sim/time/total_running_time_sec", "readonly")

-- Touchdown speed data
dataref("ma_ias_kts", "sim/cockpit2/gauges/indicators/airspeed_kts_pilot", "readonly")
dataref("ma_tas_kts", "sim/cockpit2/gauges/indicators/true_airspeed_kts_pilot", "readonly")

-- Angle of attack
dataref("ma_aoa_deg", "sim/flightmodel/position/alpha", "readonly")

-- Wind information.
-- If a specific aircraft does not feed these correctly, replace these two datarefs later.
dataref("ma_wind_speed_kts", "sim/cockpit2/gauges/indicators/wind_speed_kts", "readonly")
dataref("ma_wind_heading_deg_mag", "sim/cockpit2/gauges/indicators/wind_heading_deg_mag", "readonly")
dataref("ma_heading_deg_mag", "sim/flightmodel/position/mag_psi", "readonly")

-- =========================
-- Internal State
-- =========================

local armed = false
local was_on_ground = 1

local vs_samples = {}

local last_airborne_vs_fpm = 0
local selected_final_vs_fpm = 0

local last_airborne_ias_kts = 0
local last_airborne_tas_kts = 0
local last_airborne_gs_kts = 0
local last_airborne_aoa_deg = 0
local last_airborne_roll_deg = 0
local last_airborne_wind_speed_kts = 0
local last_airborne_wind_heading_deg = 0
local last_airborne_heading_deg = 0

local landing_active = false
local landing_complete = false
local g_capture_until = 0
local g_samples = {}

local landing_fpm = 0
local landing_touch_g = 1.00
local landing_peak_g = 1.00
local landing_g = 1.00
local landing_ias_kts = 0
local landing_tas_kts = 0
local landing_gs_kts = 0
local landing_aoa_deg = 0
local landing_roll_deg = 0
local landing_wind_speed_kts = 0
local landing_wind_heading_deg = 0
local landing_heading_deg = 0
local landing_wind_relative_text = ""
local landing_status = "STABLE"
local landing_timestamp = ""

local debug_last_frame_fpm = 0
local debug_selected_fpm = 0
local debug_touch_g = 0
local debug_peak_g = 0
local debug_robust_g = 0
local debug_expected_max_g = 0
local debug_used_g = 0

local show_until = 0
local taxi_popup_done = false
local settings_window = nil

local POSITION_OPTIONS = {
    { id = "top_left", label = "Top left" },
    { id = "top_center", label = "Top center" },
    { id = "top_right", label = "Top right" },
    { id = "middle_left", label = "Middle left" },
    { id = "center", label = "Center" },
    { id = "middle_right", label = "Middle right" },
    { id = "bottom_left", label = "Bottom left" },
    { id = "bottom_center", label = "Bottom center" },
    { id = "bottom_right", label = "Bottom right" }
}

-- =========================
-- Utility
-- =========================

local function round_num(n)
    if n >= 0 then
        return math.floor(n + 0.5)
    else
        return math.ceil(n - 0.5)
    end
end

local function mps_to_kt(mps)
    return mps * 1.943844
end

local function meters_to_feet(m)
    return m * 3.28084
end

local function abs_value(v)
    if v < 0 then return -v end
    return v
end

local function normalize_deg(deg)
    local d = deg % 360
    if d < 0 then d = d + 360 end
    return d
end

local function angular_diff_180(from_deg, to_deg)
    -- Returns signed shortest difference from aircraft heading to wind direction.
    -- Negative = wind from left side. Positive = wind from right side.
    local diff = normalize_deg(from_deg - to_deg)
    if diff > 180 then diff = diff - 360 end
    return diff
end

local function build_wind_relative_text(wind_from_deg, wind_speed_kts, aircraft_heading_deg)
    -- X-Plane wind heading is the direction the wind is FROM.
    -- Six relative categories are used for a more precise landing readout:
    -- 顶风 / 左前侧风 / 右前侧风 / 左后侧风 / 右后侧风 / 顺风
    local diff = angular_diff_180(wind_from_deg, aircraft_heading_deg)
    local abs_diff = abs_value(diff)
    local side = "顶风"

    if abs_diff <= 20 then
        side = "顶风"
    elseif abs_diff >= 160 then
        side = "顺风"
    elseif diff < 0 and abs_diff <= 90 then
        side = "左前侧风"
    elseif diff > 0 and abs_diff <= 90 then
        side = "右前侧风"
    elseif diff < 0 then
        side = "左后侧风"
    else
        side = "右后侧风"
    end

    return string.format("风 %03d/%dkt %s", round_num(normalize_deg(wind_from_deg)), round_num(wind_speed_kts), side)
end

local function format_roll_text(roll_deg)
    -- X-Plane phi is normally positive for right bank and negative for left bank.
    -- Very tiny values are treated as level to avoid distracting +/-0.1° flicker.
    local abs_roll = abs_value(roll_deg)
    if abs_roll < 0.05 then
        return "横滚 LEVEL 0.0°"
    elseif roll_deg < 0 then
        return string.format("横滚 L %.1f°", abs_roll)
    else
        return string.format("横滚 R %.1f°", abs_roll)
    end
end

local function classify_landing(fpm, g, external_hint)
    local abs_fpm = abs_value(fpm)
    local level = 0
    -- 0 = stable, 1 = attention, 2 = unstable

    if abs_fpm > FPM_ATTENTION_MAX or g > G_ATTENTION_MAX then
        level = 2
    elseif abs_fpm > FPM_STABLE_MAX or g > G_STABLE_MAX then
        level = 1
    end

    -- External score interface reserved for future use.
    if external_hint == "UNSTABLE" then
        level = math.max(level, 2)
    elseif external_hint == "ATTENTION" then
        level = math.max(level, 1)
    end

    if level == 2 then
        return "UNSTABLE"
    elseif level == 1 then
        return "ATTENTION"
    else
        return "STABLE"
    end
end

local function status_color(status)
    if status == "UNSTABLE" then
        return 0.85, 0.08, 0.05, PANEL_ALPHA
    elseif status == "ATTENTION" then
        return 0.95, 0.70, 0.05, PANEL_ALPHA
    else
        return 0.05, 0.45, 0.10, PANEL_ALPHA
    end
end

local function status_short(status)
    if status == "UNSTABLE" then
        return "UNSTABLE"
    elseif status == "ATTENTION" then
        return "ATTENTION"
    else
        return "STABLE"
    end
end

local function clear_vs_samples()
    vs_samples = {}
end

local function add_vs_sample(now, vs_fpm)
    table.insert(vs_samples, { t = now, vs = vs_fpm })

    local cutoff = now - VS_SAMPLE_WINDOW_SECONDS
    while #vs_samples > 0 and vs_samples[1].t < cutoff do
        table.remove(vs_samples, 1)
    end
end

local function select_final_vs_fpm()
    if #vs_samples == 0 then
        return last_airborne_vs_fpm
    end

    if FPM_CAPTURE_MODE == "last_frame" then
        return last_airborne_vs_fpm
    end

    -- Use strongest downward rate in final window.
    -- In X-Plane this often correlates better with touchdown G than the last airborne frame,
    -- because the last frame may already be affected by wheel contact / dataref smoothing.
    local min_vs = vs_samples[1].vs
    for i = 2, #vs_samples do
        if vs_samples[i].vs < min_vs then
            min_vs = vs_samples[i].vs
        end
    end

    return min_vs
end

local function clear_g_samples()
    g_samples = {}
end

local function sanitize_g(g)
    -- Normal touchdown G should be positive and within a sane range.
    -- Do not use abs(g): a bad negative spike should not become a hard landing.
    if g == nil then return nil end
    if g > 0.5 and g < 3.0 then
        return g
    end
    return nil
end

local function add_g_sample(now, g)
    local clean_g = sanitize_g(g)
    if clean_g == nil then return end

    table.insert(g_samples, { t = now, g = clean_g })

    local cutoff = now - G_CAPTURE_SECONDS
    while #g_samples > 0 and g_samples[1].t < cutoff do
        table.remove(g_samples, 1)
    end
end

local function select_robust_g()
    if #g_samples == 0 then
        return landing_touch_g
    end

    local values = {}
    for i = 1, #g_samples do
        values[i] = g_samples[i].g
    end
    table.sort(values)

    -- Very short sample sets cannot form a useful percentile; use max in that case.
    if #values < 4 then
        return values[#values]
    end

    local index = math.ceil(#values * G_ROBUST_PERCENTILE)
    if index < 1 then index = 1 end
    if index > #values then index = #values end

    return values[index]
end

local function estimate_g_from_fpm(fpm)
    -- Simple physical sanity estimate:
    -- touchdown load roughly depends on sink-rate energy being arrested over gear/strut time.
    -- It is not meant to replace measured G; it only prevents obviously impossible pairings.
    local sink_mps = abs_value(fpm) * 0.00508
    local extra_g = sink_mps / (G_FPM_DECEL_TIME_SECONDS * 9.80665)
    return 1.0 + extra_g
end

local function max_logical_g_from_fpm(fpm)
    local abs_fpm = abs_value(fpm)
    local margin = G_LOGIC_MARGIN_HARD

    if abs_fpm <= 150 then
        margin = G_LOGIC_MARGIN_SOFT
    elseif abs_fpm <= 300 then
        margin = G_LOGIC_MARGIN_NORMAL
    end

    return estimate_g_from_fpm(fpm) + margin
end

local function compute_landing_g(fpm)
    local robust_g = select_robust_g()
    local logical_cap_g = max_logical_g_from_fpm(fpm)
    local used_g = robust_g

    if ENABLE_G_FPM_LOGIC_GUARD == true and used_g > logical_cap_g then
        used_g = logical_cap_g
    end

    if used_g < 1.0 then
        used_g = 1.0
    end

    return used_g, robust_g, logical_cap_g
end

local function draw_panel_border(x, y, w, h)
    glColor4f(1, 1, 1, 0.18)
    glRectf(x, y + h - 1, x + w, y + h)
    glRectf(x, y, x + w, y + 1)
    glRectf(x, y, x + 1, y + h)
    glRectf(x + w - 1, y, x + w, y + h)
end

local function current_sim_time()
    if ma_running_time_sec ~= nil then
        return ma_running_time_sec
    end
    return os.clock()
end

local function is_valid_position(position_id)
    for i = 1, #POSITION_OPTIONS do
        if POSITION_OPTIONS[i].id == position_id then
            return true
        end
    end
    return false
end

local function position_label(position_id)
    for i = 1, #POSITION_OPTIONS do
        if POSITION_OPTIONS[i].id == position_id then
            return POSITION_OPTIONS[i].label
        end
    end
    return "Middle left"
end

local function calculate_popup_position(screen_w, screen_h, panel_w, panel_h)
    local margin = 30
    local x = margin
    local y = math.floor((screen_h - panel_h) / 2)

    if POPUP_POSITION == "top_left" or POPUP_POSITION == "top_center" or POPUP_POSITION == "top_right" then
        y = screen_h - panel_h - margin
    elseif POPUP_POSITION == "bottom_left" or POPUP_POSITION == "bottom_center" or POPUP_POSITION == "bottom_right" then
        y = margin
    end

    if POPUP_POSITION == "top_center" or POPUP_POSITION == "center" or POPUP_POSITION == "bottom_center" then
        x = math.floor((screen_w - panel_w) / 2)
    elseif POPUP_POSITION == "top_right" or POPUP_POSITION == "middle_right" or POPUP_POSITION == "bottom_right" then
        x = screen_w - panel_w - margin
    end

    if x < 0 then x = 0 end
    if y < 0 then y = 0 end
    if x + panel_w > screen_w then x = math.max(0, screen_w - panel_w) end
    if y + panel_h > screen_h then y = math.max(0, screen_h - panel_h) end

    return x, y
end

local settings_save_ok = true

local function save_settings()
    local file, err = io.open(SETTINGS_FILE_PATH, "w")
    if file == nil then
        settings_save_ok = false
        if logMsg then
            logMsg("[StarLux LMM] Unable to save settings: " .. tostring(err))
        end
        return false
    end

    file:write("# StarLux Landing Meter settings\n")
    file:write("popup_mode=" .. POPUP_MODE .. "\n")
    file:write("display_seconds=" .. tostring(DISPLAY_SECONDS) .. "\n")
    file:write("popup_position=" .. POPUP_POSITION .. "\n")
    file:write("debug_mode=" .. tostring(DEBUG_MODE) .. "\n")
    file:close()
    settings_save_ok = true
    return true
end

local function load_settings()
    local file = io.open(SETTINGS_FILE_PATH, "r")
    if file == nil then
        save_settings()
        return
    end

    for line in file:lines() do
        local key, value = line:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
        if key == "popup_mode" and (value == "touchdown" or value == "taxi") then
            POPUP_MODE = value
        elseif key == "display_seconds" then
            local seconds = tonumber(value)
            if seconds == 30 or seconds == 60 or seconds == 120 then
                DISPLAY_SECONDS = seconds
            end
        elseif key == "popup_position" and is_valid_position(value) then
            POPUP_POSITION = value
        elseif key == "debug_mode" then
            DEBUG_MODE = value == "true"
        end
    end
    file:close()
end

local function ensure_log_directory()
    local command
    if PATH_SEPARATOR == "\\" then
        command = 'mkdir "' .. LOG_DIRECTORY_PATH .. '" >NUL 2>NUL'
    else
        command = 'mkdir -p "' .. LOG_DIRECTORY_PATH .. '" >/dev/null 2>&1'
    end
    os.execute(command)
end

local function status_explanation(status)
    if status == "UNSTABLE" then
        return "不稳定：下降率或过载超过不稳定阈值"
    elseif status == "ATTENTION" then
        return "需注意：下降率或过载超过稳定阈值"
    end
    return "稳定：下降率和过载均在稳定阈值内"
end

local function roll_log_text(roll_deg)
    local abs_roll = abs_value(roll_deg)
    if abs_roll < 0.05 then
        return "水平（0.0 deg）"
    elseif roll_deg < 0 then
        return string.format("左倾 %.1f deg", abs_roll)
    end
    return string.format("右倾 %.1f deg", abs_roll)
end

local function vertical_speed_log_text(fpm)
    if fpm <= 0 then
        return string.format("%d fpm（向下 %d fpm）", fpm, abs_value(fpm))
    end
    return string.format("+%d fpm（向上）", fpm)
end

local function position_log_label(position_id)
    local labels = {
        top_left = "左上",
        top_center = "上方居中",
        top_right = "右上",
        middle_left = "左侧居中",
        center = "屏幕中央",
        middle_right = "右侧居中",
        bottom_left = "左下",
        bottom_center = "下方居中",
        bottom_right = "右下"
    }
    return labels[position_id] or "左侧居中"
end

local function next_log_file_path()
    local base_name = "LMM_" .. os.date("%Y-%m-%d_%H-%M-%S")
    local suffix = 0

    while suffix < 1000 do
        local file_name
        if suffix == 0 then
            file_name = base_name .. ".txt"
        else
            file_name = string.format("%s_%02d.txt", base_name, suffix)
        end

        local path = join_path(LOG_DIRECTORY_PATH, file_name)
        local existing = io.open(path, "r")
        if existing == nil then
            return path
        end
        existing:close()
        suffix = suffix + 1
    end

    return join_path(LOG_DIRECTORY_PATH, base_name .. "_extra.txt")
end

local function write_landing_log()
    ensure_log_directory()
    local log_path = next_log_file_path()
    local file, err = io.open(log_path, "w")
    if file == nil then
        if logMsg then
            logMsg("[StarLux LMM] Unable to write landing log: " .. tostring(err))
        end
        return false
    end

    file:write("\239\187\191")
    file:write("StarLux 落地率插件 - 单次落地记录\n")
    file:write("============================================================\n")
    file:write("落地时间（本地时间）: " .. landing_timestamp .. "\n")
    file:write("落地评价: " .. landing_status .. "\n")
    file:write("评价说明: " .. status_explanation(landing_status) .. "\n\n")

    file:write("触地数据\n")
    file:write("------------------------------------------------------------\n")
    file:write("触地垂直速度: " .. vertical_speed_log_text(landing_fpm) .. "\n")
    file:write(string.format("最终过载: %.2f G\n", landing_g))
    file:write(string.format("指示空速（IAS）: %.0f kt\n", landing_ias_kts))
    file:write(string.format("真空速（TAS）: %.0f kt\n", landing_tas_kts))
    file:write(string.format("地速（GS）: %.0f kt\n", landing_gs_kts))
    file:write(string.format("迎角: %.1f deg\n", landing_aoa_deg))
    file:write("横滚角: " .. roll_log_text(landing_roll_deg) .. "\n")
    file:write(string.format("飞机磁航向: %03d deg\n", round_num(normalize_deg(landing_heading_deg))))
    file:write(string.format("风向和风速: 来自 %03d deg，%d kt\n", round_num(normalize_deg(landing_wind_heading_deg)), round_num(landing_wind_speed_kts)))
    file:write("相对风: " .. landing_wind_relative_text .. "\n\n")

    file:write("测量明细\n")
    file:write("------------------------------------------------------------\n")
    file:write(string.format("触地帧过载: %.2f G\n", landing_touch_g))
    file:write(string.format("短窗口原始峰值: %.2f G\n", landing_peak_g))
    file:write(string.format("稳健采样值: %.2f G\n", debug_robust_g))
    file:write(string.format("FPM/G 一致性上限: %.2f G\n", debug_expected_max_g))
    file:write(string.format("最终显示和评分值: %.2f G\n\n", landing_g))

    file:write("评分阈值\n")
    file:write("------------------------------------------------------------\n")
    file:write(string.format("稳定上限: 下降率不大于 %d fpm，过载不大于 %.2f G\n", FPM_STABLE_MAX, G_STABLE_MAX))
    file:write(string.format("注意上限: 下降率不大于 %d fpm，过载不大于 %.2f G\n", FPM_ATTENTION_MAX, G_ATTENTION_MAX))
    file:write("超过任意注意上限时，评价为 UNSTABLE。\n\n")

    file:write("本次使用的显示设置\n")
    file:write("------------------------------------------------------------\n")
    file:write("弹窗时机: " .. (POPUP_MODE == "touchdown" and "触地时" or "地速低于 30 kt 时") .. "\n")
    file:write("显示时长: " .. tostring(DISPLAY_SECONDS) .. " 秒\n")
    file:write("屏幕位置: " .. position_log_label(POPUP_POSITION) .. "\n")
    file:close()

    if logMsg then
        logMsg("[StarLux LMM] Landing log saved: " .. log_path)
    end
    return true
end

ensure_log_directory()
load_settings()

-- =========================
-- Settings Window
-- =========================

function ma_settings_window_closed(wnd)
    settings_window = nil
end

function ma_open_settings_window()
    if not SUPPORTS_FLOATING_WINDOWS then
        if logMsg then
            logMsg("[StarLux LMM] This FlyWithLua version does not support floating windows.")
        end
        return
    end

    if settings_window ~= nil then
        return
    end

    settings_window = float_wnd_create(520, 430, 1, true)
    float_wnd_set_title(settings_window, "StarLux Landing Meter - Settings")
    float_wnd_set_imgui_builder(settings_window, "ma_build_settings_window")
    float_wnd_set_onclose(settings_window, "ma_settings_window_closed")

    local screen_w = SCREEN_WIDTH or 1920
    local screen_h = SCREEN_HIGHT or 1080
    float_wnd_set_position(settings_window, math.floor((screen_w - 520) / 2), math.floor((screen_h - 430) / 2))
end

function ma_build_settings_window(wnd, x, y)
    imgui.TextUnformatted("Landing data popup timing")
    if imgui.RadioButton("Show at touchdown", POPUP_MODE == "touchdown") then
        POPUP_MODE = "touchdown"
        save_settings()
    end
    if imgui.RadioButton("Show after slowing below 30 kt", POPUP_MODE == "taxi") then
        POPUP_MODE = "taxi"
        save_settings()
    end

    imgui.Separator()
    imgui.TextUnformatted("Popup duration")
    if imgui.RadioButton("30 seconds", DISPLAY_SECONDS == 30) then
        DISPLAY_SECONDS = 30
        save_settings()
    end
    imgui.SameLine()
    if imgui.RadioButton("60 seconds", DISPLAY_SECONDS == 60) then
        DISPLAY_SECONDS = 60
        save_settings()
    end
    imgui.SameLine()
    if imgui.RadioButton("120 seconds (maximum)", DISPLAY_SECONDS == 120) then
        DISPLAY_SECONDS = 120
        save_settings()
    end

    imgui.Separator()
    imgui.TextUnformatted("Popup position")
    if imgui.BeginCombo("Screen position##lmm_position", position_label(POPUP_POSITION)) then
        for i = 1, #POSITION_OPTIONS do
            local option = POSITION_OPTIONS[i]
            if imgui.Selectable(option.label, POPUP_POSITION == option.id) then
                POPUP_POSITION = option.id
                save_settings()
            end
        end
        imgui.EndCombo()
    end

    imgui.Separator()
    local changed, new_debug_value = imgui.Checkbox("Show measurement debug details", DEBUG_MODE)
    if changed then
        DEBUG_MODE = new_debug_value
        save_settings()
    end

    if imgui.Button("Preview popup for 5 seconds", 220, 28) then
        show_until = current_sim_time() + 5
    end

    imgui.Separator()
    if settings_save_ok then
        imgui.TextUnformatted("Settings are saved automatically.")
    else
        imgui.TextUnformatted("Warning: settings could not be saved. Check FlyWithLua Log.txt.")
    end
    imgui.TextUnformatted("Each completed landing is saved as a TXT file in:")
    imgui.TextUnformatted(LOG_DIRECTORY_PATH)
end

add_macro("StarLux Landing Meter | Open Settings", "ma_open_settings_window()")
create_command(
    "starlux/lmm/open_settings",
    "Open StarLux Landing Meter settings",
    "ma_open_settings_window()",
    "",
    ""
)

-- =========================
-- Core Logic
-- =========================

function ma_landing_meter_update()
    local now = current_sim_time()

    local radio_alt_ft = meters_to_feet(ma_y_agl_m)
    local gs_kt = mps_to_kt(ma_groundspeed_mps)
    local current_g = ma_g_normal

    -- Arm only after aircraft is airborne enough.
    -- This prevents popup when loading the aircraft already parked on ground.
    if ma_on_ground == 0 and radio_alt_ft > 20 and gs_kt > 50 then
        if armed == false then
            clear_vs_samples()
            clear_g_samples()
        end
        armed = true
        landing_complete = false
        taxi_popup_done = false
    end

    -- While airborne near landing, keep the final approach data snapshot.
    -- The final VS buffer is intentionally limited to low AGL.
    if ma_on_ground == 0 and armed == true and radio_alt_ft < 500 then
        last_airborne_vs_fpm = ma_vs_fpm
        last_airborne_ias_kts = ma_ias_kts
        last_airborne_tas_kts = ma_tas_kts
        last_airborne_gs_kts = gs_kt
        last_airborne_aoa_deg = ma_aoa_deg
        last_airborne_roll_deg = ma_roll_deg
        last_airborne_wind_speed_kts = ma_wind_speed_kts
        last_airborne_wind_heading_deg = ma_wind_heading_deg_mag
        last_airborne_heading_deg = ma_heading_deg_mag

        if radio_alt_ft <= VS_SAMPLE_MAX_AGL_FT then
            add_vs_sample(now, ma_vs_fpm)
        end
    end

    -- Touchdown detection: transition from airborne to on-ground.
    if armed == true and was_on_ground == 0 and ma_on_ground == 1 and gs_kt > 35 then
        landing_active = true
        landing_complete = false
        landing_timestamp = os.date("%Y-%m-%d %H:%M:%S")

        selected_final_vs_fpm = select_final_vs_fpm()
        landing_fpm = round_num(selected_final_vs_fpm)

        clear_g_samples()
        local clean_touch_g = sanitize_g(current_g)
        if clean_touch_g == nil then
            clean_touch_g = 1.00
        end

        landing_touch_g = clean_touch_g
        landing_peak_g = clean_touch_g
        landing_g = clean_touch_g
        add_g_sample(now, clean_touch_g)

        landing_ias_kts = last_airborne_ias_kts
        landing_tas_kts = last_airborne_tas_kts
        landing_gs_kts = last_airborne_gs_kts
        landing_aoa_deg = last_airborne_aoa_deg
        landing_roll_deg = last_airborne_roll_deg
        landing_wind_speed_kts = last_airborne_wind_speed_kts
        landing_wind_heading_deg = last_airborne_wind_heading_deg
        landing_heading_deg = last_airborne_heading_deg
        landing_wind_relative_text = build_wind_relative_text(
            landing_wind_heading_deg,
            landing_wind_speed_kts,
            landing_heading_deg
        )

        debug_last_frame_fpm = round_num(last_airborne_vs_fpm)
        debug_selected_fpm = landing_fpm
        debug_touch_g = landing_touch_g
        debug_peak_g = landing_peak_g
        debug_robust_g = landing_touch_g
        debug_expected_max_g = max_logical_g_from_fpm(landing_fpm)
        debug_used_g = landing_g

        g_capture_until = now + G_CAPTURE_SECONDS

        if POPUP_MODE == "touchdown" then
            show_until = now + DISPLAY_SECONDS
        end
    end

    -- Capture peak G shortly after touchdown.
    if landing_active == true then
        -- Collect sane G samples only. Raw peak is still stored for debug,
        -- but it is no longer directly trusted for scoring/display.
        local clean_current_g = sanitize_g(current_g)
        if clean_current_g ~= nil then
            add_g_sample(now, clean_current_g)
            if clean_current_g > landing_peak_g then
                landing_peak_g = clean_current_g
            end
        end

        debug_peak_g = landing_peak_g

        if now >= g_capture_until then
            if USE_PEAK_G_FOR_SCORE then
                landing_g, debug_robust_g, debug_expected_max_g = compute_landing_g(landing_fpm)
            else
                landing_g = landing_touch_g
                debug_robust_g = landing_touch_g
                debug_expected_max_g = max_logical_g_from_fpm(landing_fpm)
            end
            debug_used_g = landing_g

            landing_status = classify_landing(landing_fpm, landing_g, EXTERNAL_SCORE_HINT)
            landing_active = false
            landing_complete = true
            armed = false
            clear_vs_samples()
            clear_g_samples()

            if logMsg then
                logMsg(string.format(
                    "[StarLux LMM] FPM last=%d selected=%d | G touch=%.2f rawPeak=%.2f robust=%.2f cap=%.2f used=%.2f | IAS=%.0f GS=%.0f AoA=%.1f Roll=%.1f | Wind=%03d/%dkt | WindRel=%s | Mode=%s",
                    debug_last_frame_fpm,
                    debug_selected_fpm,
                    landing_touch_g,
                    landing_peak_g,
                    debug_robust_g,
                    debug_expected_max_g,
                    landing_g,
                    landing_ias_kts,
                    landing_gs_kts,
                    landing_aoa_deg,
                    landing_roll_deg,
                    round_num(normalize_deg(landing_wind_heading_deg)),
                    round_num(landing_wind_speed_kts),
                    landing_wind_relative_text,
                    POPUP_MODE
                ))
            end

            write_landing_log()
        end
    end

    -- Taxi popup mode: show when speed below 30 kt after landing.
    if POPUP_MODE == "taxi" and landing_complete == true and taxi_popup_done == false then
        if gs_kt <= TAXI_POPUP_SPEED_KT then
            show_until = now + DISPLAY_SECONDS
            taxi_popup_done = true
        end
    end

    was_on_ground = ma_on_ground
end

-- =========================
-- Drawing
-- =========================

function ma_landing_meter_draw()
    local now = current_sim_time()

    if show_until <= 0 or now > show_until then
        return
    end

    local screen_w = SCREEN_WIDTH or 1920
    local screen_h = SCREEN_HIGHT or 1080

    local panel_w = PANEL_W
    local panel_h = PANEL_H

    local x, y = calculate_popup_position(screen_w, screen_h, panel_w, panel_h)

    local r, g, b, a = status_color(landing_status)

    XPLMSetGraphicsState(0, 0, 0, 1, 1, 0, 0)

    -- Compact translucent background
    glColor4f(r, g, b, a)
    glRectf(x, y, x + panel_w, y + panel_h)
    draw_panel_border(x, y, panel_w, panel_h)

    -- Text
    glColor4f(1, 1, 1, 0.96)

    local line1 = string.format("%+d fpm | +%.2fG", landing_fpm, landing_g)
    local line2 = string.format("IAS %.0fkt | GS %.0fkt", landing_ias_kts, landing_gs_kts)
    local line3 = string.format("迎角 %.1f° | %s", landing_aoa_deg, format_roll_text(landing_roll_deg))
    local line4 = landing_wind_relative_text
    local line5 = status_short(landing_status)

    draw_string(x + 14, y + 88, line1)
    draw_string(x + 14, y + 66, line2)
    draw_string(x + 14, y + 44, line3)
    draw_string(x + 14, y + 22, line4)
    draw_string(x + 14, y + 5, line5)

    if DEBUG_MODE == true then
        glColor4f(1, 1, 1, 0.86)
        local debug_line1 = string.format("DBG FPM last:%d sel:%d", debug_last_frame_fpm, debug_selected_fpm)
        local debug_line2 = string.format("DBG G touch:%.2f rawPk:%.2f", debug_touch_g, debug_peak_g)
        local debug_line3 = string.format("DBG G rb:%.2f cap:%.2f used:%.2f", debug_robust_g, debug_expected_max_g, debug_used_g)
        local debug_x = x + panel_w + 12
        if debug_x + 270 > screen_w then
            debug_x = math.max(0, x - 282)
        end
        draw_string(debug_x, y + 70, debug_line1)
        draw_string(debug_x, y + 48, debug_line2)
        draw_string(debug_x, y + 26, debug_line3)
    end
end

do_every_frame("ma_landing_meter_update()")
do_every_draw("ma_landing_meter_draw()")
