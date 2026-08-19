# alt_web01

`alt_web01` 是一个用于演示大学生入学、在校与毕业过程的 Flask 模拟系统框架。当前版本完成网站结构、导航和部署骨架，各业务页面暂以页面名称作为占位内容。

## 主要页面

- 学生：手工添加、小数据量批量添加、大数据量批量添加
- 大学：手工添加大学、手工添加专业组、自动添加大学和专业组
- 入学：手动入学、自动入学
- 统计分析：历年学生数量、各大学学生数量

所有页面继承 `base.html`，并通过 Bootstrap 5.3.8 下拉菜单统一导航。

## 项目结构

```text
.
├── src/alt_web01/
│   ├── __init__.py          # Flask 应用工厂
│   ├── views.py             # 演示页面路由
│   ├── static/css/site.css  # 网站样式
│   └── templates/
│       ├── base.html        # 导航与公共布局
│       └── page.html        # 页面名称占位模板
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
