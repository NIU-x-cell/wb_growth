"""
WB运营人员成长分析系统 - 配置文件
本地MySQL / 线上TiDB Cloud 通用配置
"""
import os

# ============================================================
# 数据库配置
# ============================================================
# 本地开发环境（PyCharm + MySQL）
DB_CONFIG_LOCAL = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",       # 改成你本地MySQL密码
    "database": "wb_growth",
    "charset": "utf8mb4",
}

# 线上TiDB Cloud配置（部署时使用，先留空）
DB_CONFIG_TIDB = {
    "host": "gateway01.ap-northeast-1.prod.aws.tidbcloud.com",
    "port": 4000,
    "user": "2Laq9LZGesfBWbb.root",
    "password": "xS7GiG5cdZlWjqJV",
    "database": "wb_growth",
    "charset": "utf8mb4",
    "ssl_verify_cert": True,
    "ssl_verify_identity": True,
}

# 当前使用的环境: "local" 或 "tidb"
ENV = os.getenv("WB_ENV", "tidb")

def get_db_config():
    """根据环境返回数据库配置"""
    if ENV == "tidb":
        return DB_CONFIG_TIDB
    return DB_CONFIG_LOCAL


# ============================================================
# 数据文件路径
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

PERSON_FILE = os.path.join(DATA_DIR, "wb人员名单.xlsx")
ORDER_FILE = os.path.join(DATA_DIR, "wb成长.xlsx")


# ============================================================
# 分析配置
# ============================================================
# 有效订单状态（计入业绩的订单）
VALID_ORDER_STATUS = ["已发货", "已完成"]

# 时间粒度选项
TIME_GRANULARITY = {
    "按周": "W",
    "按月": "M",
    "按日": "D",
}

# 看板默认时间范围（天）
DEFAULT_DAYS = 90

# 业绩指标定义
METRICS = {
    "销售额": "商品总金额",
    "订单数": "订单编号",
    "退款金额": "退款金额",
    "广告费": "广告费(人民币)",
    "成本": "商品总成本",
}
