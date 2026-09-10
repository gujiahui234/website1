# alt_web01

`alt_web01` 是一个用于演示大学生入学、在校与毕业过程的 Flask 模拟系统框架。当前版本已实现手工添加学生、手工维护学生信息、手工添加大学和手工添加专业组流程，其余业务页面暂以页面名称作为占位内容。

## 主要页面

- 学生：手工添加、小数据量批量添加、大数据量批量添加、手工维护学生信息
- 大学：手工添加大学、手工添加专业组、自动添加大学和专业组
- 入学：手动入学、自动入学
- 统计分析：历年学生数量、各大学学生数量

所有页面继承 `base.html`，并通过 Bootstrap 5.3.8 下拉菜单统一导航。

### 手工添加学生

- 可录入姓名、生日和性别；生日范围为 `2000-01-01` 至 `2020-12-31`
- “自动生成”通过 `class-roster-simulator` 生成一名虚构学生并回填表单
- Docker 部署时，“保存学生”写入 `/opt/dockers/mysql` 中独立运行的 MySQL；本地未配置时仍可使用内存模式
- Flask 请求、异常与保存成功事件通过 `sclog_lite` 输出到控制台和 `logs/`

### 手工维护学生信息

- 位于一级菜单“学生”下的二级菜单页面（`/students/maintain`）
- 数据通过已建立的**学生 API 服务器**（poc4-students-api，FastAPI）读写，不使用 MCP 发现，
  服务器调试/文档地址在 `.env` 中配置：
  - `API_SERVER_DOCS` — Swagger UI 调试页
  - `API_SERVER_REDOC` — ReDoc 文档页
  - `API_SERVER_JSON` — OpenAPI JSON（同时用于推导服务器基地址）
- 支持按姓名模糊匹配、按性别（M/F）过滤搜索学生列表，单次最多返回 1000 条
- 支持按学生记录 ID 精确查询单个学生
- 点击搜索结果中的学生行弹出编辑框，可修改姓名、性别、出生日期；
  也可在警告确认后删除该学生记录
- 页面请求先到达 Flask 同源 JSON 代理端点
  （`/students/maintain/api/students*`），由 `alt_web01/api_client.py`
  （httpx）转发到 API 服务器，避免跨域问题

### 手工添加大学

- 可录入高校名称、五位数字高校国标代码、高校类型和高校性质
- 高校名称与高校代码均不可重复，MySQL 模式使用数据库唯一索引保证约束
- 页面下方使用 DataTable 展示、搜索、排序和分页浏览全部已保存高校

### 手工添加专业组

- 从已保存高校中选择一所，再录入专业组名称和二至五位数字代码
- 专业组名称与代码在同一所高校内不可重复，不同高校可使用相同值
- 切换高校后，DataTable 只展示所选高校的全部专业组

## 项目结构

```text
.
├── src/alt_web01/
│   ├── __init__.py          # Flask 应用工厂
│   ├── api_client.py        # 学生 API 服务器（poc4）HTTP 客户端
│   ├── views/               # 按页面拆分的路由模块
│   │   ├── __init__.py      # 共享 Blueprint 与模块注册
│   │   ├── common.py        # 通用页面渲染工具
│   │   └── *.py             # 每个页面一个路由文件
│   ├── static/css/site.css  # 网站样式
│   └── templates/
│       ├── base.html        # 导航与公共布局
│       ├── page.html        # 页面名称占位模板
│       ├── student_add.html # 手工添加学生页面
│       └── student_maintain.html # 手工维护学生信息页面
├── tests/test_students.py   # 学生录入流程测试
├── wsgi.py                  # 容器 WSGI 入口
├── pyproject.toml           # PEP 517 / PEP 621 项目配置
├── Dockerfile
└── docker-compose.yml
```

## 本地运行

需要 Python 3.13 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python app.py
```

打开 <http://127.0.0.1:5000>。

## Docker 运行

```powershell
docker compose up --build
```

打开 <http://127.0.0.1:8800>。停止服务时运行：

```powershell
docker compose down
```

部署前在项目目录创建 `.env`（不要提交），填写独立 MySQL 已有的普通应用账户：

```dotenv
MYSQL_DATABASE=test_db
MYSQL_USER=test_user
MYSQL_PASSWORD=使用 /opt/dockers/mysql/.env 中现有的 MYSQL_PASSWORD

# 学生 API 服务器（poc4-students-api）调试与文档地址
API_SERVER_DOCS=http://192.168.220.134:8001/docs
API_SERVER_REDOC=http://192.168.220.134:8001/redoc
API_SERVER_JSON=http://192.168.220.134:8001/openapi.json
```

网站容器会加入 MySQL 使用的外部 `app-network`，通过容器名 `mysql-server:3306`
连接。应用会拒绝 `MYSQL_USER=root`，并自动创建 `students` 表。
