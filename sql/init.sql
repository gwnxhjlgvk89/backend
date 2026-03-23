-- 创建数据库
-- CREATE DATABASE IF NOT EXISTS club_selection CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- 1. 专业表（设计了学院，用于后续仅导出某学院选课数据）
CREATE TABLE majors (
    -- 直接限制专业名称唯一，避免后续维护一个自增ID反而增加复杂度
    major_name VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '专业名称',
    department VARCHAR(64) NOT NULL COMMENT '所属学院/系部',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) COMMENT = '专业表';

-- 2. 班级表（后续建立学生表，因为需要外键关联）
CREATE TABLE classes (
    class_name VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '班级名称',
    major_name VARCHAR(64) NOT NULL COMMENT '所属专业名称',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY fk_class_major (major_name) REFERENCES majors(major_name)
) COMMENT = '班级表';

-- 3. 学生表（核心表）
CREATE TABLE students (
    student_id VARCHAR(20) NOT NULL PRIMARY KEY COMMENT '学号（登录账号）',
    name VARCHAR(32) NOT NULL COMMENT '姓名',
    avatar VARCHAR(255) NULL COMMENT '头像URL',
    email VARCHAR(64) NULL COMMENT '邮箱地址',
    phone VARCHAR(20) NULL COMMENT '联系电话',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
    class_name VARCHAR(64) NOT NULL COMMENT '班级名称',
    major_name VARCHAR(64) NOT NULL COMMENT '专业名称（冗余存储，方便查询）',
    department VARCHAR(64) NOT NULL COMMENT '学院/系部（冗余存储，方便查询）',
    is_pwd_changed TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已修改初始密码',
    account_status TINYINT(1) NOT NULL DEFAULT 1 COMMENT '账号状态 1-正常 0-禁用',
    is_reserved TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否在预留名单中 0-不在 1-在',
    reserved_club_name VARCHAR(64) NULL COMMENT '预留社团名称（冗余存储，方便查询）',
    -- 抢课模式：只关心有没有抢到
    has_selected TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已抢到社团 0-未抢到 1-已抢到',
    -- 这里的select_club_name不加外键，因为抢课过程中会频繁更新这个字段，如果加外键会导致性能问题，改成冗余存储，定期通过后台任务校验数据一致性
    selected_club_name VARCHAR(64) NULL COMMENT '已抢到的社团名称（冗余存储）',
    selected_at DATETIME NULL COMMENT '抢到时间',
    token_ver INTEGER DEFAULT 1 NOT NULL COMMENT 'token版号，确保同时只有一人登录',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY fk_stu_class (class_name) REFERENCES classes(class_name),
    FOREIGN KEY fk_stu_major (major_name) REFERENCES majors(major_name),
    INDEX idx_has_selected (has_selected),
    INDEX idx_selected_club (selected_club_name)
) COMMENT = '学生表';

-- 4. 社团表（核心表）
CREATE TABLE clubs (
    club_name VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '社团名称',
    teacher_advisor VARCHAR(32) NULL COMMENT '指导老师',
    club_president VARCHAR(32) NULL COMMENT '社长',
    super_club VARCHAR(32) NOT NULL COMMENT '一级社团',
    description TEXT NULL COMMENT '社团简介(Card页展示)',
    description_detail TEXT NULL COMMENT '社团详细介绍(详情页展示)',
    cover_image VARCHAR(255) NULL COMMENT '封面图片URL',
    activity_position VARCHAR(64) NULL COMMENT '社团活动位置',
    activity_time VARCHAR(64) NULL COMMENT '社团活动时间',
    foundation_year YEAR NULL COMMENT '社团成立年份',
    -- 名额管理（抢课核心字段）
    total_quota SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '总名额',
    reserved_quota SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '预留名额（管理员预留给特定学生）',
    remaining_quota SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '剩余名额（实时扣减）',
    -- 专业限制
    has_major_limit TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否限制专业 0-不限 1-限制',
    -- 状态控制
    club_status TINYINT NOT NULL DEFAULT 0 COMMENT '社团状态 0-未开放 1-抢课中 2-名额已满 3-已结束',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_club_name (club_name),
    INDEX idx_club_status (club_status),
    INDEX idx_remaining_quota (remaining_quota)
) COMMENT = '社团表';

CREATE TABLE club_activities (
    activity_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '活动ID',
    club_name VARCHAR(64) NOT NULL COMMENT '社团名称',
    activity_name VARCHAR(64) NOT NULL COMMENT '活动名称',
    activity_location VARCHAR(64) NULL COMMENT '活动地点',
    FOREIGN KEY fk_activity_club (club_name) REFERENCES clubs(club_name) ON DELETE CASCADE
) COMMENT = '社团活动表';

-- 5. 学生收藏表（多对多关系，学生可以收藏多个社团，社团也可以被多个学生收藏）
CREATE TABLE student_favorites (
    student_id VARCHAR(20) NOT NULL COMMENT '学号',
    club_name VARCHAR(64) NOT NULL COMMENT '社团名称',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '收藏时间',
    -- 联合主键：同一个学生不能重复收藏同一个社团
    PRIMARY KEY (student_id, club_name),
    -- 外键：学生删除时级联删除收藏记录
    FOREIGN KEY fk_fav_student (student_id) REFERENCES students (student_id) ON DELETE CASCADE,
    -- 外键：社团删除时级联删除收藏记录
    FOREIGN KEY fk_fav_club (club_name) REFERENCES clubs (club_name) ON DELETE CASCADE
) COMMENT = '学生收藏社团中间表';

-- 6. 社团专业限制表（多对多关系）
CREATE TABLE club_major_restrictions (
    club_name VARCHAR(64) NOT NULL COMMENT '社团名称',
    major_name VARCHAR(64) NOT NULL COMMENT '允许报名的专业名称',
    FOREIGN KEY fk_cmr_club (club_name) REFERENCES clubs(club_name) ON DELETE CASCADE,
    FOREIGN KEY fk_cmr_major (major_name) REFERENCES majors(major_name) ON DELETE CASCADE,
    PRIMARY KEY uk_club_major (club_name, major_name)
) COMMENT = '社团专业限制表';

-- 7. 抢课记录表（核心表，记录每次成功抢课的详情）
CREATE TABLE selections (
    selection_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '记录ID',
    student_id VARCHAR(20) NOT NULL COMMENT '学号',
    club_name VARCHAR(64) NOT NULL COMMENT '社团名称',
    selected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '抢到时间',
    FOREIGN KEY fk_sel_student (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
    FOREIGN KEY fk_sel_club (club_name) REFERENCES clubs(club_name) ON DELETE CASCADE,
    UNIQUE KEY uk_student_selection (student_id) COMMENT '每个学生只能抢一个社团',
    INDEX idx_club_name (club_name),
    INDEX idx_selected_at (selected_at)
) COMMENT = '抢课成功记录表';

-- 8. 预留名单表（用于管理员预留名额给特定学生，优先于正常抢课流程）
CREATE TABLE reserved_list (
    student_id VARCHAR(20) NOT NULL PRIMARY KEY COMMENT '学号',
    club_name VARCHAR(64) NOT NULL COMMENT '预留社团名称',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by INT UNSIGNED NULL COMMENT '操作管理员ID',
    FOREIGN KEY fk_rl_student (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
    FOREIGN KEY fk_rl_club (club_name) REFERENCES clubs(club_name) ON DELETE CASCADE
) COMMENT = '预留名单表';

-- 9. 管理员表（用于系统管理，非学生用户）
CREATE TABLE admin_users (
    admin_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '管理员ID',
    username VARCHAR(32) NOT NULL COMMENT '管理员账号',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
    real_name VARCHAR(32) NULL COMMENT '真实姓名',
    role TINYINT NOT NULL DEFAULT 1 COMMENT '角色 1-普通管理员 2-超级管理员',
    is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
    last_login_at DATETIME NULL COMMENT '最后登录时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_username (username)
) COMMENT = '管理员表';

-- 10. 系统配置表（核心表，控制抢课流程和规则）
CREATE TABLE system_config (
    config_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    activity_name VARCHAR(64) NOT NULL DEFAULT '社团招新' COMMENT '活动名称',
    -- 时间节点
    preview_start DATETIME NULL COMMENT '预览开始时间（可提前看社团信息）',
    preview_end DATETIME NULL COMMENT '预览结束时间',
    select_start DATETIME NULL COMMENT '抢课开始时间',
    select_end DATETIME NULL COMMENT '抢课结束时间',
    -- 规则配置
    allow_cancel TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否允许学生退课 0-不允许 1-允许',
    cancel_deadline DATETIME NULL COMMENT '退课截止时间',
    -- 系统状态
    system_status TINYINT NOT NULL DEFAULT 0 COMMENT '0-未发布 1-预览中 2-抢课进行中 3-已结束',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) COMMENT = '系统配置表';

-- 11. 操作日志表（记录管理员操作和重要事件，便于审计和问题排查）
CREATE TABLE operation_logs (
    log_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    operator_id VARCHAR(32) NOT NULL COMMENT '操作者ID',
    operator_type TINYINT NOT NULL COMMENT '1-学生 2-管理员',
    action VARCHAR(64) NOT NULL COMMENT '操作类型',
    target_table VARCHAR(32) NULL,
    target_id VARCHAR(32) NULL,
    detail JSON NULL COMMENT '操作详情（前后对比等）',
    ip_address VARCHAR(45) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_operator (operator_id, operator_type),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at)
) COMMENT = '操作日志表';