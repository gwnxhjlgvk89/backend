-- 删除当前数据库下的所有表
SET
    FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS reserved_list;

DROP TABLE IF EXISTS club_major_restrictions;

DROP TABLE IF EXISTS student_favorites;

DROP TABLE IF EXISTS selections;

DROP TABLE IF EXISTS club_activities;

DROP TABLE IF EXISTS clubs;

DROP TABLE IF EXISTS admin_users;

DROP TABLE IF EXISTS students;

DROP TABLE IF EXISTS classes;

DROP TABLE IF EXISTS majors;

DROP TABLE IF EXISTS system_config;

DROP TABLE IF EXISTS operation_logs;

SET
    FOREIGN_KEY_CHECKS = 1;