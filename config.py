"""
WB运营人员成长分析系统 - 配置文件
本地MySQL / 线上TiDB Cloud 通用配置

使用方式：
- 本地开发：默认使用本地MySQL（ENV="local"）
- 线上部署：设置环境变量 WB_ENV=tidb，自动切换到TiDB Cloud
  Streamlit Cloud 中在 Secrets 里配置 WB_ENV=tidb 及以下 TIDB_* 变量
"""
import os

# ============================================================
# 数据库配置
# ============================================================



# ---------- 线上TiDB Cloud配置（Streamlit Cloud部署时使用） ----------
# 在 TiDB Cloud 控制台创建 Serverless 集群后，把连接信息填到下面
# 或在 Streamlit Cloud → Secrets 中配置 TIDB_HOST / TIDB_USER / TIDB_PASSWORD
DB_CONFIG_TIDB = {
    "host": os.getenv("TIDB_HOST", "your-cluster.gateway01.region.tidbcloud.com"),
    "port": int(os.getenv("TIDB_PORT", 4000)),
    "user": os.getenv("TIDB_USER", "your_user.root"),
    "password": os.getenv("TIDB_PASSWORD", "your_password"),
    "database": os.getenv("TIDB_DB_NAME", "wb_growth"),
    "charset": "utf8mb4",
    "ssl_verify_cert": True,
    "ssl_verify_identity": True,
}

# 当前使用的环境: "local" 或 "tidb"
# 本地运行默认 local；Streamlit Cloud 部署时在 Secrets 里设 WB_ENV=tidb
ENV = os.getenv("WB_ENV", "tidb")


def get_db_config():
    """根据环境返回数据库配置"""
    if ENV == "tidb":
        return DB_CONFIG_TIDB
    return DB_CONFIG_LOCAL



# ============================================================
# 分析配置
# ============================================================
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
