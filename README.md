# alt_web01

`alt_web01` 是一个用于演示大学生入学、在校与毕业过程的 Flask 模拟系统框架。当前版本已实现手工添加学生、手工添加大学和手工添加专业组流程，其余业务页面暂以页面名称作为占位内容。

## 主要页面

- 学生：手工添加、小数据量批量添加、大数据量批量添加
- 大学：手工添加大学、手工添加专业组、自动添加大学和专业组
- 入学：手动入学、自动入学
- 统计分析：历年学生数量、各大学学生数量

所有页面继承 `base.html`，并通过 Bootstrap 5.3.8 下拉菜单统一导航。

### 手工添加学生

- 可录入姓名、生日和性别；生日范围为 `2000-01-01` 至 `2020-12-31`
- “自动生成”通过 `class-roster-simulator` 生成一名虚构学生并回填表单
- Docker 部署时，“保存学生”写入 `/opt/dockers/mysql` 中独立运行的 MySQL；本地未配置时仍可使用内存模式
- Flask 请求、异常与保存成功事件通过 `sclog_lite` 输出到控制台和 `logs/`

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
│   ├── views/               # 按页面拆分的路由模块
│   │   ├── __init__.py      # 共享 Blueprint 与模块注册
│   │   ├── common.py        # 通用页面渲染工具
│   │   └── *.py             # 每个页面一个路由文件
│   ├── static/css/site.css  # 网站样式
│   └── templates/
│       ├── base.html        # 导航与公共布局
│       ├── page.html        # 页面名称占位模板
│       └── student_add.html # 手工添加学生页面
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
```

网站容器会加入 MySQL 使用的外部 `app-network`，通过容器名 `mysql-server:3306`
连接。应用会拒绝 `MYSQL_USER=root`，并自动创建 `students` 表。
