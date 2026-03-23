import random
from datetime import datetime, timedelta
import openpyxl
from openpyxl import Workbook

# ─── 基础数据池 ───────────────────────────────────────────

DEPARTMENTS = {
    "信息工程学院": ["软件工程", "计算机科学与技术", "网络工程", "人工智能"],
    "经济管理学院": ["工商管理", "市场营销", "会计学", "财务管理"],
    "文学与传媒学院": ["汉语言文学", "新闻学", "广播电视学", "网络与新媒体"],
    "理学院": ["数学与应用数学", "物理学", "统计学"],
    "外国语学院": ["英语", "日语", "商务英语"],
    "艺术设计学院": ["视觉传达设计", "环境设计", "数字媒体艺术"],
}

# 专业 → 学院 映射
MAJOR_TO_DEPT = {}
for dept, majors in DEPARTMENTS.items():
    for m in majors:
        MAJOR_TO_DEPT[m] = dept

ALL_MAJORS = list(MAJOR_TO_DEPT.keys())

# 班级：每个专业 2 个班
CLASSES = []
for major in ALL_MAJORS:
    CLASSES.append(f"{major}2301班")
    CLASSES.append(f"{major}2302班")

CLASS_TO_MAJOR = {c: c.replace("2301班", "").replace("2302班", "") for c in CLASSES}

SURNAMES = list("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜")
NAMES_POOL = list("伟芳娜秀英敏静冰雪梅丽娟文明磊建国志强海燕鹏宇辉博")


def random_name():
    return random.choice(SURNAMES) + "".join(
        random.choices(NAMES_POOL, k=random.choice([1, 2]))
    )


def random_phone():
    prefixes = [
        "130",
        "131",
        "132",
        "133",
        "135",
        "136",
        "137",
        "138",
        "139",
        "150",
        "151",
        "152",
        "153",
        "155",
        "156",
        "158",
        "159",
        "170",
        "171",
        "173",
        "175",
        "176",
        "177",
        "178",
        "180",
        "181",
        "182",
        "183",
        "185",
        "186",
        "187",
        "188",
        "189",
    ]
    return random.choice(prefixes) + "".join(
        [str(random.randint(0, 9)) for _ in range(8)]
    )


def random_date(start_year=2023, end_year=2024):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    return start + timedelta(days=random.randint(0, (end - start).days))


# ─── 生成 200 名学生 ──────────────────────────────────────

wb_students = Workbook()
ws = wb_students.active
ws.title = "学生数据"

headers = [
    "student_id",
    "name",
    "avatar",
    "email",
    "phone",
    "class_name",
    "major_name",
    "department",
    "is_pwd_changed",
    "account_status",
    "has_selected",
    "selected_club_id",
    "selected_at",
    "created_at",
]
ws.append(headers)

used_ids = set()
student_count = 200

for i in range(student_count):
    # 学号：2023 + 6位随机数
    while True:
        sid = "2023" + str(random.randint(100000, 999999))
        if sid not in used_ids:
            used_ids.add(sid)
            break

    name = random_name()
    class_name = random.choice(CLASSES)
    major_name = CLASS_TO_MAJOR[class_name]
    department = MAJOR_TO_DEPT[major_name]
    email = f"{sid}@stu.example.edu.cn"
    phone = random_phone()
    created_at = random_date(2023, 2024).strftime("%Y-%m-%d %H:%M:%S")

    ws.append(
        [
            sid,  # student_id
            name,  # name
            "",  # avatar（空）
            email,  # email
            phone,  # phone
            class_name,  # class_name
            major_name,  # major_name
            department,  # department
            0,  # is_pwd_changed（未修改初始密码）
            1,  # account_status（正常）
            0,  # has_selected（未抢到）
            "",  # selected_club_id（空）
            "",  # selected_at（空）
            created_at,  # created_at
        ]
    )

wb_students.save("students_test_data.xlsx")
print(f"✅ 学生数据已生成：students_test_data.xlsx（{student_count} 条）")


# ─── 生成 40 个社团 ───────────────────────────────────────

CLUB_TEMPLATES = [
    # (名称, 简介, 活动位置, 活动时间, 成立年份, 总名额, 是否限专业, 限制专业列表)
    (
        "篮球协会",
        "热爱篮球，欢迎所有球友加入",
        "体育馆A区",
        "每周二、四 18:00-20:00",
        2015,
        60,
        0,
        [],
    ),
    (
        "足球俱乐部",
        "校园足球文化推广，定期举办联赛",
        "操场南区",
        "每周三、六 17:30-19:30",
        2016,
        50,
        0,
        [],
    ),
    (
        "羽毛球协会",
        "提升羽毛球技术，享受运动乐趣",
        "体育馆B区",
        "每周一、五 19:00-21:00",
        2017,
        40,
        0,
        [],
    ),
    (
        "乒乓球协会",
        "乒乒乓乓，活力无限",
        "体育馆C区",
        "每周二 18:00-20:00",
        2018,
        35,
        0,
        [],
    ),
    (
        "舞蹈社",
        "涵盖流行舞、民族舞、现代舞等多种形式",
        "艺术楼301",
        "每周三、五 19:00-21:00",
        2014,
        45,
        0,
        [],
    ),
    (
        "吉他社",
        "学习吉他，感受音乐之美",
        "艺术楼201",
        "每周四 18:30-20:30",
        2016,
        30,
        0,
        [],
    ),
    (
        "钢琴社",
        "专业钢琴学习与交流平台",
        "音乐厅",
        "每周六 14:00-17:00",
        2013,
        20,
        0,
        [],
    ),
    (
        "合唱团",
        "用歌声传递情感，弘扬校园文化",
        "音乐厅",
        "每周二、四 19:00-21:00",
        2012,
        50,
        0,
        [],
    ),
    (
        "话剧社",
        "戏剧创作与表演，挑战自我",
        "大礼堂",
        "每周五 18:00-21:00",
        2015,
        35,
        0,
        [],
    ),
    (
        "辩论社",
        "思维碰撞，提升表达与逻辑能力",
        "教学楼A201",
        "每周三 19:00-21:00",
        2014,
        40,
        0,
        [],
    ),
    (
        "摄影协会",
        "记录生活之美，学习摄影技术",
        "艺术楼402",
        "每周六 10:00-12:00",
        2016,
        35,
        0,
        [],
    ),
    (
        "书法协会",
        "传承中华书法文化",
        "文化活动中心",
        "每周日 14:00-16:00",
        2011,
        30,
        0,
        [],
    ),
    (
        "国画社",
        "学习国画技艺，感受传统文化魅力",
        "艺术楼305",
        "每周六 14:00-17:00",
        2013,
        25,
        0,
        [],
    ),
    (
        "动漫社",
        "二次元文化交流，cosplay活动",
        "学生活动中心",
        "每周五 19:00-21:00",
        2017,
        50,
        0,
        [],
    ),
    (
        "读书会",
        "分享好书，拓宽视野",
        "图书馆三楼",
        "每周日 15:00-17:00",
        2015,
        40,
        0,
        [],
    ),
    (
        "志愿者协会",
        "服务社会，传递温暖",
        "志愿服务中心",
        "每周末不定期",
        2010,
        80,
        0,
        [],
    ),
    (
        "环保协会",
        "绿色环保，从我做起",
        "综合楼101",
        "每周三 18:00-20:00",
        2014,
        45,
        0,
        [],
    ),
    (
        "创业协会",
        "孵化创业梦想，连接资源与机会",
        "创新创业中心",
        "每周四 19:00-21:00",
        2016,
        40,
        0,
        [],
    ),
    (
        "英语角",
        "英语交流与学习，外教定期参与",
        "图书馆一楼",
        "每周二 18:30-20:00",
        2012,
        60,
        0,
        [],
    ),
    (
        "日语学习社",
        "日语入门到进阶，日本文化交流",
        "教学楼B302",
        "每周三、五 18:00-19:30",
        2018,
        30,
        0,
        [],
    ),
    (
        "编程俱乐部",
        "算法竞赛、项目开发、技术分享",
        "实验楼301",
        "每周二、四 19:00-21:30",
        2017,
        40,
        1,
        ["软件工程", "计算机科学与技术", "网络工程", "人工智能"],
    ),
    (
        "人工智能社",
        "探索AI前沿技术，动手实践机器学习项目",
        "实验楼405",
        "每周三 19:00-21:00",
        2020,
        30,
        1,
        ["软件工程", "计算机科学与技术", "人工智能", "数学与应用数学"],
    ),
    (
        "网络安全社",
        "CTF竞赛训练，网络攻防技术学习",
        "实验楼302",
        "每周五 18:00-21:00",
        2019,
        25,
        1,
        ["软件工程", "计算机科学与技术", "网络工程"],
    ),
    (
        "数据科学社",
        "数据分析、可视化与建模实战",
        "实验楼403",
        "每周四 18:30-21:00",
        2021,
        25,
        1,
        ["软件工程", "人工智能", "统计学", "数学与应用数学"],
    ),
    (
        "财经研究社",
        "金融市场分析，模拟投资与财经新闻解读",
        "经管楼201",
        "每周三 18:00-20:00",
        2016,
        35,
        1,
        ["工商管理", "市场营销", "会计学", "财务管理"],
    ),
    (
        "电商运营社",
        "实战电商平台运营，新媒体营销",
        "经管楼305",
        "每周二、四 18:00-20:00",
        2019,
        40,
        1,
        ["工商管理", "市场营销", "网络与新媒体"],
    ),
    (
        "新闻传媒社",
        "校园新闻采编，视频制作与传播",
        "传媒楼201",
        "每周一、三 18:00-20:00",
        2015,
        35,
        1,
        ["新闻学", "广播电视学", "网络与新媒体", "汉语言文学"],
    ),
    (
        "微电影社",
        "剧本创作、拍摄与后期制作全流程学习",
        "传媒楼305",
        "每周五、六 14:00-18:00",
        2018,
        25,
        1,
        ["广播电视学", "网络与新媒体", "数字媒体艺术", "视觉传达设计"],
    ),
    (
        "UI设计社",
        "界面设计与用户体验研究",
        "艺术楼401",
        "每周三、五 18:30-20:30",
        2020,
        30,
        1,
        ["视觉传达设计", "数字媒体艺术", "软件工程", "计算机科学与技术"],
    ),
    (
        "插画创作社",
        "数字插画与手绘技法交流",
        "艺术楼306",
        "每周六 13:00-17:00",
        2019,
        25,
        1,
        ["视觉传达设计", "数字媒体艺术", "环境设计"],
    ),
    (
        "数学建模社",
        "参加全国数学建模竞赛，培养数学应用能力",
        "理学楼301",
        "每周二、四 19:00-21:00",
        2014,
        30,
        1,
        ["数学与应用数学", "统计学", "软件工程", "人工智能"],
    ),
    (
        "物理实验社",
        "趣味物理实验设计与科普活动",
        "理学楼实验室",
        "每周六 14:00-17:00",
        2016,
        20,
        1,
        ["物理学", "数学与应用数学"],
    ),
    (
        "文学创作社",
        "诗歌、散文、小说创作与分享",
        "文学院201",
        "每周四 18:00-20:00",
        2013,
        40,
        1,
        ["汉语言文学", "新闻学", "英语", "日语"],
    ),
    (
        "翻译实践社",
        "英日双语翻译练习，笔译口译双向培训",
        "外语楼302",
        "每周三、五 18:00-19:30",
        2017,
        30,
        1,
        ["英语", "日语", "商务英语"],
    ),
    (
        "心理健康协会",
        "心理知识普及，减压活动与朋辈辅导",
        "心理健康中心",
        "每周二 18:00-20:00",
        2015,
        50,
        0,
        [],
    ),
    (
        "棋牌协会",
        "围棋、象棋、国际象棋多项目发展",
        "学生活动中心",
        "每周日 14:00-17:00",
        2014,
        35,
        0,
        [],
    ),
    (
        "跑步社",
        "晨跑、夜跑，打卡健身，参加马拉松",
        "操场",
        "每天 06:30-07:15",
        2018,
        100,
        0,
        [],
    ),
    (
        "瑜伽健身社",
        "瑜伽冥想与力量训练结合，健康生活方式",
        "体育馆D区",
        "每周一、三、五 19:00-20:30",
        2019,
        30,
        0,
        [],
    ),
    (
        "天文观测社",
        "天文知识学习，望远镜观测星空",
        "楼顶观测台",
        "每月1-3次夜间活动",
        2016,
        25,
        0,
        [],
    ),
    (
        "厨艺交流社",
        "各地美食制作分享，烹饪技能学习",
        "学生活动中心烹饪室",
        "每周六 15:00-18:00",
        2020,
        30,
        0,
        [],
    ),
]

wb_clubs = Workbook()
ws_clubs = wb_clubs.active
ws_clubs.title = "社团数据"

club_headers = [
    "club_id",
    "club_name",
    "description",
    "description_detail",
    "cover_image",
    "activity_position",
    "activity_time",
    "foundation_year",
    "total_quota",
    "remaining_quota",
    "has_major_limit",
    "allowed_majors（逗号分隔）",
    "club_status",
    "created_at",
]
ws_clubs.append(club_headers)

for idx, t in enumerate(CLUB_TEMPLATES, start=1):
    name, desc, pos, time_str, year, quota, has_limit, majors = t
    detail = f"{name}是一个充满活力的学生组织。{desc}。我们定期举办各类活动，欢迎对{name.replace('协会','').replace('社','').replace('俱乐部','')}感兴趣的同学加入！"
    created_at = random_date(int(str(year)), int(str(year))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    ws_clubs.append(
        [
            idx,  # club_id
            name,  # club_name
            desc,  # description
            detail,  # description_detail
            "",  # cover_image（空）
            pos,  # activity_position
            time_str,  # activity_time
            year,  # foundation_year
            quota,  # total_quota
            quota,  # remaining_quota（初始 = 总名额）
            has_limit,  # has_major_limit
            "、".join(majors) if majors else "不限",  # allowed_majors
            0,  # club_status（未开放）
            created_at,  # created_at
        ]
    )

wb_clubs.save("clubs_test_data.xlsx")
print(f"✅ 社团数据已生成：clubs_test_data.xlsx（{len(CLUB_TEMPLATES)} 条）")

print("\n📋 专业-学院数据（可直接导入 majors 表）：")
for major, dept in MAJOR_TO_DEPT.items():
    print(f"  {major} → {dept}")

print("\n📋 班级数据（可直接导入 classes 表）：")
for c in CLASSES:
    print(f"  {c} → {CLASS_TO_MAJOR[c]}")
