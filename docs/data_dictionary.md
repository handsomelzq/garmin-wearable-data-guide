# 数据字典

三张正式数据表使用英文 snake_case 字段。以下仅是字段定义，不含受访者数据。

## daily_data

| 变量名 | 中文含义 | 单位或格式 | 来源与处理 |
|---|---|---|---|
| subject_id | 受试者编码 | 文本标识 | 数据整理时生成，使用本地配置提供的受访者编号 |
| local_date | 本地日期 | YYYY-MM-DD | 按 Asia/Shanghai 归属日整理 |
| heart_rate_observation_count | 当天有效心率观测数 | 次 | FIT monitoring有效心率30≤HR<255；按原始时刻和值去重后计数，分钟无读数计数为0 |
| heart_rate_mean_bpm | 当天有效心率均值 | bpm | FIT 解码 csv/monitoring.csv；按 local_date 聚合 |
| heart_rate_min_bpm | 当天有效心率最小值 | bpm | FIT 解码 csv/monitoring.csv；按 local_date 聚合 |
| heart_rate_max_bpm | 当天有效心率最大值 | bpm | FIT 解码 csv/monitoring.csv；按 local_date 聚合 |
| fit_cycles | FIT 重算累计步数的周期折算值 | 步周期/原始计数 | FIT csv/monitoring.csv；按活动类型取每日最大值后汇总，主要用于核查 |
| distance_m | 官方日距离 | m | Garmin Connect服务器日汇总 official/json/<日期>.json：totalDistanceMeters；源字段缺失时留空 |
| active_calories_kcal | 官方日活动热量 | kcal | Garmin Connect服务器日汇总 official/json/<日期>.json：activeKilocalories；源字段缺失时留空 |
| active_time_s | 官方日活动时间 | s | 服务器日汇总：activeSeconds + highlyActiveSeconds；任一缺失则为空 |
| resting_heart_rate_bpm | 当天静息心率 | bpm | Garmin Connect服务器日汇总 official/json/<日期>.json：restingHeartRate；源字段缺失时留空 |
| stress_valid_observation_count | 有效压力观测数 | 次 | FIT stress_level_value在0—100内的有效记录数；负值及异常值不参与统计 |
| stress_mean_score | 有效压力均值 | 0–100等级 | FIT csv/stress_level.csv；按 local_date 聚合 |
| stress_max_score | 有效压力最大值 | 0–100等级 | FIT csv/stress_level.csv |
| stress_observation_count | 压力原始观测总数 | 次 | FIT csv/stress_level.csv；含无法测量记录 |
| stress_valid_percent | 压力有效率 | % | stress_valid_observation_count / stress_observation_count × 100；无原始记录时为空 |
| moderate_intensity_minutes | 中等强度分钟 | min | Garmin Connect服务器日汇总 official/json/<日期>.json：moderateIntensityMinutes；源字段缺失时留空 |
| vigorous_intensity_minutes | 高强度分钟 | min | Garmin Connect服务器日汇总 official/json/<日期>.json：vigorousIntensityMinutes；源字段缺失时留空 |
| weighted_intensity_minutes | 加权强度分钟 | min | moderate_intensity_minutes + 2×vigorous_intensity_minutes；任一缺失则为空 |
| floors_ascended_m | 上楼/上升高度 | m | Garmin Connect服务器日汇总 official/json/<日期>.json：floorsAscendedInMeters；源字段缺失时留空 |
| floors_descended_m | 下楼/下降高度 | m | Garmin Connect服务器日汇总 official/json/<日期>.json：floorsDescendedInMeters；源字段缺失时留空 |
| body_battery_highest | 当天身体电量最高值 | 分值 0–100 | Garmin Connect服务器日汇总 official/json/<日期>.json：bodyBatteryHighestValue；源字段缺失时留空 |
| body_battery_lowest | 当天身体电量最低值 | 分值 0–100 | Garmin Connect服务器日汇总 official/json/<日期>.json：bodyBatteryLowestValue；源字段缺失时留空 |
| body_battery_charged | 当天身体电量累计充电量 | 分值 | Garmin Connect服务器日汇总 official/json/<日期>.json：bodyBatteryChargedValue；源字段缺失时留空 |
| body_battery_drained | 当天身体电量累计消耗量 | 分值 | Garmin Connect服务器日汇总 official/json/<日期>.json：bodyBatteryDrainedValue；源字段缺失时留空 |
| body_battery_at_wake | 起床时身体电量 | 分值 0–100 | Garmin Connect服务器日汇总 official/json/<日期>.json：bodyBatteryAtWakeTime；源字段缺失时留空 |
| sleep_record_valid | 睡眠记录是否通过项目质控 | 布尔值 | 服务器睡眠JSON及项目质控，原因见data/<编号>/sleep/sleep_nightly.csv |
| sleep_duration_minutes | 睡眠持续时间 | min | 官网睡眠 JSON；按起床日期合并 |
| sleep_start_local | 入睡时间 | 本地日期时间 | 官网睡眠 JSON；Asia/Shanghai |
| sleep_end_local | 起床时间 | 本地日期时间 | 官网睡眠 JSON；Asia/Shanghai |
| deep_sleep_minutes | 深睡时长 | min | 官网睡眠分期 JSON |
| light_sleep_minutes | 浅睡时长 | min | 官网睡眠分期 JSON |
| rem_sleep_minutes | REM睡眠时长 | min | 官网睡眠分期 JSON |
| awake_minutes | 清醒时长 | min | 官网睡眠分期 JSON |
| unmeasurable_sleep_minutes | 无法测量时长 | min | 官网睡眠分期 JSON |
| nap_minutes | 小睡时长 | min | 官网睡眠 JSON |
| sleep_heart_rate_mean_bpm | 睡眠期间平均心率 | bpm | 官网睡眠 JSON/睡眠汇总 |
| sleep_resting_heart_rate_bpm | 睡眠记录中的静息心率 | bpm | 官网睡眠 JSON/睡眠汇总 |
| sleep_stress_mean_score | 睡眠期间平均压力 | 0–100等级 | 官网睡眠 JSON/睡眠汇总 |
| sleep_body_battery_change | 睡眠期间身体电量变化 | 分值 | 官网睡眠 JSON/睡眠汇总 |
| running_steps | 跑步步数 | 步 | FIT csv/monitoring.csv；running 活动类型累计值 |
| walking_steps | 步行步数 | 步 | FIT csv/monitoring.csv；walking 活动类型累计值 |
| official_total_steps | 官方日总步数 | 步 | Garmin Connect服务器日汇总 official/json/<日期>.json：totalSteps；源字段缺失时留空 |

## minute_data

| 变量名 | 中文含义 | 单位或格式 | 来源与处理 |
|---|---|---|---|
| subject_id | 受试者编码 | 文本标识 | 数据整理时生成 |
| source_file | 心率或压力来源FIT文件名 | 文本文件名 | 本分钟压力、有效心率及有效血氧的来源文件并集，分号分隔 |
| minute_start_local | 分钟起始时间 | 北京时间 YYYY-MM-DD HH:mm | 由 FIT 时间戳统一转换为 Asia/Shanghai，并向下归入对应分钟。 |
| local_date | 本地日期 | YYYY-MM-DD | 由北京时间分钟键提取；每天固定1440行。 |
| stress_record_time_utc | 该分钟首条压力记录的原始时间 | UTC日期时间 | csv/stress_level.csv；本列为UTC，local_time为UTC+8。 |
| stress_score | 该分钟有效压力读数的均值 | 0–100分 | csv/stress_level.csv；去除跨文件重复记录；仅0–100参与均值；负值或缺测留空，不插值。 |
| manufacturer_field_2 | 未公开字段2的末条非空值 | 未核定 | FIT压力表厂商字段；未验证含义，仅保留备查，不作生理指标解释。 |
| body_battery_score_estimate | 分钟身体电量均值（项目解释） | 分值 | FIT压力表字段3；为既有项目解释，非官方公开字段定义。 |
| manufacturer_status_code | 未公开状态码的末条非空值 | 状态码 | FIT压力表字段4；保留代码不取平均，不直接据此推断未佩戴。 |
| heart_rate_mean_bpm | 该分钟有效心率读数的均值 | bpm（次/分钟） | FIT monitoring心率30≤HR<255；按原始时刻和值去重后分钟算术均值；缺测留空 |
| heart_rate_observation_count | 该分钟去重后有效心率观测数 | 次 | FIT monitoring有效心率30≤HR<255；按原始时刻和值去重后计数，分钟无读数计数为0 |
| stress_valid_observation_count | 该分钟去重后有效压力观测数 | 次 | FIT stress_level_value在0—100内的有效记录数；负值及异常值不参与统计 |
| stress_raw_observation_count | 该分钟去重后压力观测总数 | 次 | 包括负值状态记录；无记录为0；不是压力大小或秒数。 |
| spo2_reading_time_local | 血氧测量本地时间 | 北京时间日期时间 | 该分钟第一条有效FIT血氧读数的真实时间，Asia/Shanghai |
| spo2_reading_time_utc | 血氧测量原始时间 | UTC 日期时间 | 该分钟第一条有效FIT血氧读数的真实时间，UTC |
| spo2_percent | 该分钟有效血氧读数均值 | % | FIT真实血氧记录；同一分钟多条有效观测取均值，不用服务器日均或小时均值展开 |
| spo2_confidence_score | 该分钟血氧置信度均值 | 分值（官方未定义单位） | FIT reading_confidence分钟均值，不能解释为准确率百分比 |
| spo2_measurement_mode | 血氧测量模式 | 文本/代码 | FIT血氧mode的分钟去重集合，分号分隔；代码不取平均 |

## activities

| 变量名 | 中文含义 | 单位或格式 | 来源与处理 |
|---|---|---|---|
| subject_id | 受试者编码 | 文本标识 | 数据整理时增加 |
| activity_id | 活动唯一编号 | 整数ID | Garmin Connect 活动摘要 raw/activities/activities.json |
| activity_type | 活动类型英文代码 | 文本 | 官网活动摘要activityType.typeKey |
| activity_start_local | 活动开始本地时间 | 本地日期时间 | Garmin Connect 活动摘要 startTimeLocal |
| is_favorite | 是否标记为最爱 | 布尔值 | Garmin Connect 活动摘要 isFavorite |
| activity_name | 活动标题 | 文本 | Garmin Connect 活动摘要 activityName |
| distance_km | 活动距离 | km | 活动摘要 distance（m）换算 |
| calories_kcal | 活动消耗热量 | kcal | 活动摘要 calories |
| duration_s | 活动计时器时长 | s | 活动摘要 duration |
| average_heart_rate_bpm | 活动平均心率 | bpm | 活动摘要 averageHR |
| maximum_heart_rate_bpm | 活动最大心率 | bpm | 活动摘要 maxHR |
| average_cadence_spm | 平均步频 | steps/min | 活动摘要 averageRunningCadenceInStepsPerMinute |
| maximum_cadence_spm | 最大步频 | steps/min | 活动摘要 maxRunningCadenceInStepsPerMinute |
| average_pace_min_per_km | 平均配速 | min/km（数值） | 由活动速度m/s转换：1000/(speed×60)，速度≤0留空 |
| best_pace_min_per_km | 最佳配速 | min/km（数值） | 由活动速度m/s转换：1000/(speed×60)，速度≤0留空 |
| average_stride_length_m | 平均步长 | m | 活动摘要avgStrideLength，厘米除100转换为米 |
| training_stress_score | 训练压力分数 | 分值 | 活动摘要不存在相应字段时留空，不填默认0或否 |
| activity_steps | 活动步数 | 步 | 活动摘要 steps |
| stress_relief_activity | 是否减压活动 | 文本/是否 | 活动摘要不存在相应字段时留空，不填默认0或否 |
| best_lap_duration_s | 最佳单圈时间 | s | 活动摘要 minActivityLapDuration |
| lap_count | 活动圈数 | 圈 | 活动摘要 lapCount |
| moving_duration_s | 移动时长 | s | 活动摘要 movingDuration |
| elapsed_duration_s | 全程耗时 | s | 活动摘要 elapsedDuration |
