# alt_web01

`alt_web01` 是一个用于演示大学生入学、在校与毕业过程的 Flask 模拟系统框架。当前版本已实现手工添加学生流程，其余业务页面暂以页面名称作为占位内容。

## 主要页面

- 学生：手工添加、小数据量批量添加、大数据量批量添加
- 大学：手工添加大学、手工添加专业组、自动添加大学和专业组
- 入学：手动入学、自动入学
- 统计分析：历年学生数量、各大学学生数量

所有页面继承 `base.html`，并通过 Bootstrap 5.3.8 下拉菜单统一导航。

### 手工添加学生

- 可录入姓名、生日和性别；生日范围为 `2000-01-01` 至 `2020-12-31`
- “自动生成”通过 `class-roster-simulator` 生成一名虚构学生并回填表单
- “保存学生”暂存到当前应用进程，在页面下方展示，不写入数据库
- Flask 请求、异常与保存成功事件通过 `sclog_lite` 输出到控制台和 `logs/`

## 项目结构

```text
.
├── src/alt_web01/
│   ├── __init__.py          # Flask 应用工厂
│   ├── views.py             # 演示页面路由
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
