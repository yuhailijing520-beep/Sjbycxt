# ⚽ WorldCup Oracle — 世界杯预测系统

融合 1930–2026 历史赛事大数据 + AI 实时分析的世界杯预测平台。
<img width="2088" height="1332" alt="image" src="https://github.com/user-attachments/assets/3b77fd54-3627-4619-bcf1-c280cf317407" />

## 技术架构

| 层级 | 技术 |
|------|------|
| 前端 | HTML/CSS/JS（可升级为 Next.js） |
| 后端 | FastAPI (Python) |
| AI   | Google Gemini Pro / GPT-4o-mini |
| 缓存 | Redis |
| 数据库 | PostgreSQL |
| 部署 | Docker Compose + Nginx |
| 新闻 | News API |

## 快速部署（推荐 · Docker 部署）

### 第一步：克隆项目
```bash
git clone https://github.com/yourname/worldcup-oracle.git
cd worldcup-oracle
```

### 第二步：配置环境变量（.env）
```bash
cp .env.example .env
nano .env   # 填写 GEMINI_API_KEY / OPENAI_API_KEY / NEWS_API_KEY 等
```

### 第三步：一键部署
```bash
# 无域名版本
sudo bash scripts/deploy.sh

# 有域名版本（自动配置 SSL）
sudo bash scripts/deploy.sh your-domain.com
```

### 第四步：访问
- 前端：http://YOUR_SERVER_IP:8021
- API 文档：http://YOUR_SERVER_IP:8022/docs

---

## 本机 / 服务器直接部署（非 Docker）

适用于只想运行后端 API 做调试或在没有 Docker 的环境下部署。

### 1. 安装依赖（Python 3.10+）

```bash
cd worldcup-oracle/backend
python -m venv venv
source venv/bin/activate  # Windows 使用: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

可以使用 `.env`（配合 `python-dotenv`）或直接导出环境变量，例如：

```bash
export AI_PROVIDER=openai
export OPENAI_API_KEY=你的_OpenAI_Key
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o-mini
export NEWS_API_KEY=你的_News_API_Key
export ADMIN_PASSWORD=自定义管理口令
```

如使用自定义兼容模型，则将 `OPENAI_BASE_URL`、`OPENAI_MODEL` 改为对应地址与名称。

### 3. 启动 FastAPI 后端

```bash
uvicorn main:app --host 0.0.0.0 --port 8022 --reload
```

此时：

- 后端 API 文档：http://YOUR_SERVER_IP:8022/docs
- 模型配置后台：http://YOUR_SERVER_IP:8022/admin

前端可以直接用静态方式部署（例如 Nginx / Vercel / 静态托管），并将调用后端的地址指向 `http://YOUR_SERVER_IP:8022`。

## 目录结构
```
worldcup-oracle/
├── frontend/           # 前端静态文件
│   └── index.html      # 主页面
├── backend/            # FastAPI 后端
│   ├── main.py         # 主程序
│   ├── requirements.txt
│   ├── Dockerfile
│   └── init.sql        # 数据库初始化
├── nginx/              # Nginx 配置
│   └── nginx.conf
├── scripts/
│   └── deploy.sh       # 一键部署脚本
├── docker-compose.yml
└── .env.example
```

## API 接口

### 预测接口
```http
POST /api/predict
Content-Type: application/json

{
  "team_a": "Brazil",
  "team_b": "Argentina",
  "include_news": true
}
```

### 历史数据
```http
GET /api/historical/{team_a}/{team_b}
```

### 球队列表
```http
GET /api/teams
```


## 常见问题

**Q: 如何更换 AI 模型？**
修改 `.env` 中的 `AI_PROVIDER=openai`，并填写 `OPENAI_API_KEY`

**Q: 历史数据来源？**
可导入来自 Kaggle 的 FIFA World Cup 数据集（1930–2022），共 900+ 场比赛记录

**Q: 预测准确率多少？**
历史回测约 68–75%，组合 AI 新闻分析后小组赛准确率可达 72%+

## License
MIT
