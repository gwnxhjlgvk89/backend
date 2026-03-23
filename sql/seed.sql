
-- ============================================================
-- seed.sql  样例数据
-- ============================================================

-- ------------------------------------------------------------
-- 1. 专业表
-- ------------------------------------------------------------
INSERT INTO majors (major_name, department) VALUES
('计算机科学与技术', '信息工程学院'),
('软件工程',         '信息工程学院'),
('人工智能',         '信息工程学院'),
('电子信息工程',     '电子与通信学院'),
('通信工程',         '电子与通信学院'),
('机械设计制造',     '机械工程学院'),
('工商管理',         '商学院'),
('会计学',           '商学院');

-- ------------------------------------------------------------
-- 2. 班级表
-- ------------------------------------------------------------
INSERT INTO classes (class_name, major_name) VALUES
('计科2301', '计算机科学与技术'),
('计科2302', '计算机科学与技术'),
('软工2301', '软件工程'),
('人工智能2301', '人工智能'),
('电信2301', '电子信息工程'),
('通信2301', '通信工程'),
('机械2301', '机械设计制造'),
('工管2301', '工商管理');

-- ------------------------------------------------------------
-- 3. 学生表（20名学生，均未填报社团）
-- password_hash 统一为 "123456" 的 bcrypt 哈希
-- ------------------------------------------------------------
INSERT INTO students (student_id, name, password_hash, class_id, major_name, has_selected, selected_club_id, selected_at) VALUES
('2023010101', '张伟',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 1, '计算机科学与技术', 0, NULL, NULL),
('2023010102', '李娜',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 1, '计算机科学与技术', 0, NULL, NULL),
('2023010103', '王磊',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 1, '计算机科学与技术', 0, NULL, NULL),
('2023010201', '刘洋',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 2, '计算机科学与技术', 0, NULL, NULL),
('2023010202', '陈静',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 2, '计算机科学与技术', 0, NULL, NULL),
('2023020101', '赵敏',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 3, '软件工程',         0, NULL, NULL),
('2023020102', '孙浩',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 3, '软件工程',         0, NULL, NULL),
('2023020103', '周婷',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 3, '软件工程',         0, NULL, NULL),
('2023030101', '吴杰',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 4, '人工智能',         0, NULL, NULL),
('2023030102', '郑雪',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 4, '人工智能',         0, NULL, NULL),
('2023040101', '冯强',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 5, '电子信息工程',     0, NULL, NULL),
('2023040102', '蒋慧',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 5, '电子信息工程',     0, NULL, NULL),
('2023040103', '韩宇',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 5, '电子信息工程',     0, NULL, NULL),
('2023050101', '杨帆',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 6, '通信工程',         0, NULL, NULL),
('2023050102', '朱琳',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 6, '通信工程',         0, NULL, NULL),
('2023060101', '徐明',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 7, '机械设计制造',     0, NULL, NULL),
('2023060102', '马丽',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 7, '机械设计制造',     0, NULL, NULL),
('2023070101', '高峰',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 8, '工商管理',         0, NULL, NULL),
('2023070102', '林晓',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 8, '工商管理',         0, NULL, NULL),
('2023070103', '罗云',   '$2b$12$KIX9v1GqtJzHbVw3VqnXrOzFJk1mN8pQyL2dR4sT6uW0eA7cB9D', 8, '工商管理',         0, NULL, NULL);

-- ------------------------------------------------------------
-- 4. 社团表（10个社团，状态各异）
-- club_status: 0-未开放 1-抢课中 2-名额已满 3-已结束
-- ------------------------------------------------------------
INSERT INTO clubs (club_name, description, total_quota, remaining_quota, has_major_limit, club_status) VALUES
('ACM算法竞赛社',   '专注于算法竞赛训练，参加ACM/ICPC、蓝桥杯等赛事，提升编程思维与解题能力。',             30, 30, 1, 1),
('机器人创新社',     '结合硬件与软件，动手制作各类机器人，参加全国大学生机器人大赛。',                       25, 25, 1, 1),
('摄影与视觉艺术社', '学习摄影构图、后期修图技巧，定期组织外拍活动与摄影展览。',                           40, 40, 0, 1),
('篮球社',           '组织日常训练与院系友谊赛，欢迎热爱篮球的同学加入。',                                   50, 50, 0, 1),
('吉他音乐社',       '从零基础到进阶演奏，涵盖民谣、指弹、电吉他，每学期举办专场演出。',                   35, 35, 0, 1),
('创业孵化社',       '聚焦商业计划书撰写、创业实战模拟，对接校外导师资源，助力创新创业。',                   20, 20, 1, 1),
('辩论与演讲社',     '训练逻辑思维与公众表达能力，参加省级以上高校辩论联赛。',                               30, 30, 0, 1),
('3D打印与创客社',   '利用3D打印、激光切割等设备将创意变为现实，承接校内创意制作项目。',                     20, 20, 1, 1),
('读书与写作社',     '每月共读一本好书，开展读书分享会，鼓励原创文学创作与投稿。',                           45, 45, 0, 0),
('羽毛球社',         '面向全校招募羽毛球爱好者，定期举办单打、双打联赛，强身健体。',                         60, 60, 0, 0);

-- ------------------------------------------------------------
-- 5. 社团专业限制
-- ACM算法竞赛社(1)：计科、软工、人工智能
-- 机器人创新社(2)：计科、电子信息、通信工程
-- 创业孵化社(6)：工商管理、会计学
-- 3D打印与创客社(8)：机械设计制造、电子信息、计科
-- ------------------------------------------------------------
INSERT INTO club_major_restrictions (club_id, major_name) VALUES
(1, '计算机科学与技术'),
(1, '软件工程'),
(1, '人工智能'),
(2, '计算机科学与技术'),
(2, '电子信息工程'),
(2, '通信工程'),
(6, '工商管理'),
(6, '会计学'),
(8, '机械设计制造'),
(8, '电子信息工程'),
(8, '计算机科学与技术');

-- ------------------------------------------------------------
-- 6. 管理员表
-- password_hash 均为 "admin123" 的 bcrypt 哈希
-- ------------------------------------------------------------
INSERT INTO admin_users (username, password_hash, real_name, role) VALUES
('admin',      '$2b$12$PqW7vXnL3mK5oR8tU1yZeOzFJk1mN8pQyL2dR4sT6uW0eA7cB9Ef', '王建国', 2),
('moderator',  '$2b$12$PqW7vXnL3mK5oR8tU1yZeOzFJk1mN8pQyL2dR4sT6uW0eA7cB9Ef', '李秀英', 1);
