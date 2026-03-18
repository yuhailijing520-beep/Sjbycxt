"""
世界杯预测系统 — FastAPI 后端
支持：历史数据查询、AI预测（Google Gemini / OpenAI）、新闻分析
"""
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
import httpx
import json
import os
import redis
import hashlib
import asyncio
from datetime import datetime, timedelta

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()  # development | production
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
CONFIG_PATH = os.getenv("MODEL_CONFIG_PATH", "model_config.json")

app = FastAPI(title="WorldCup Oracle API", version="1.0.0")

if ENVIRONMENT == "production" and ADMIN_PASSWORD == "admin123":
    raise RuntimeError("生产环境禁止使用默认 ADMIN_PASSWORD，请通过环境变量设置强口令")

cors_origins_raw = os.getenv("CORS_ORIGINS", "*").strip()
if cors_origins_raw == "*":
    cors_origins = ["*"]
else:
    cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 配置 ────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-pro")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
NEWS_API_KEY   = os.getenv("NEWS_API_KEY", "")
REDIS_URL      = os.getenv("REDIS_URL", "redis://localhost:6379")
AI_PROVIDER    = os.getenv("AI_PROVIDER", "gemini")  # gemini | openai


class ModelConfig(BaseModel):
    ai_provider: str = AI_PROVIDER
    gemini_api_key: str = GEMINI_API_KEY
    gemini_model: str = GEMINI_MODEL
    openai_api_key: str = OPENAI_API_KEY
    openai_base_url: str = OPENAI_BASE_URL
    openai_model: str = OPENAI_MODEL
    news_api_key: str = NEWS_API_KEY


def load_config() -> ModelConfig:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ModelConfig(**data)
        except Exception:
            pass
    return ModelConfig()


def save_config(cfg: ModelConfig) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg.dict(), f, ensure_ascii=False, indent=2)


CURRENT_CONFIG = load_config()

try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
except Exception:
    r = None

# ─── 模型 ────────────────────────────────────────────────
class PredictionRequest(BaseModel):
    team_a: str
    team_b: str
    match_date: Optional[str] = None
    include_news: bool = True

class PredictionResponse(BaseModel):
    team_a: str
    team_b: str
    win_a_pct: float
    draw_pct: float
    win_b_pct: float
    prediction: str
    confidence: float
    analysis: str
    key_factors: list[str]
    historical_summary: dict
    news_insights: list[str]
    generated_at: str

# ─── 历史数据（简化版，实际应从 PostgreSQL 查询）────────
HISTORICAL_DATA = {
    ("Brazil", "Argentina"): {"h2h": 41, "brazil_wins": 19, "draws": 11, "arg_wins": 11, "brazil_goals": 68, "arg_goals": 52},
    ("Germany", "France"):   {"h2h": 29, "ger_wins": 13, "draws": 7,  "fra_wins": 9,  "ger_goals": 48, "fra_goals": 40},
    ("England", "Portugal"): {"h2h": 24, "eng_wins": 8,  "draws": 9,  "por_wins": 7,  "eng_goals": 32, "por_goals": 31},
    ("Spain",   "Croatia"):  {"h2h": 12, "spa_wins": 7,  "draws": 3,  "cro_wins": 2,  "spa_goals": 26, "cro_goals": 14},
}

def get_historical(team_a: str, team_b: str) -> dict:
    key = (team_a, team_b)
    rev = (team_b, team_a)
    return HISTORICAL_DATA.get(key) or HISTORICAL_DATA.get(rev) or {"h2h": 0, "note": "No historical data found"}

# ─── 新闻抓取 ─────────────────────────────────────────────
async def fetch_news(team_a: str, team_b: str) -> list[str]:
    if not CURRENT_CONFIG.news_api_key:
        return ["无法加载最新新闻（未配置 News API Key）"]
    url = (f"https://newsapi.org/v2/everything?"
           f"q={team_a}+{team_b}+football&"
           f"language=zh&sortBy=publishedAt&pageSize=5&"
           f"apiKey={CURRENT_CONFIG.news_api_key}")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            data = resp.json()
            return [a["title"] for a in data.get("articles", [])[:3]]
    except Exception:
        return ["新闻加载失败，使用历史数据分析"]

# ─── Gemini AI 预测 ───────────────────────────────────────
async def predict_with_gemini(team_a: str, team_b: str, history: dict, news: list) -> dict:
    if not CURRENT_CONFIG.gemini_api_key:
        raise HTTPException(status_code=503, detail="Gemini API Key 未配置")

    prompt = f"""你是世界顶级足球数据分析师，专注世界杯赛事预测。

比赛：{team_a} vs {team_b}

历史交锋数据：
{json.dumps(history, ensure_ascii=False, indent=2)}

最新相关新闻：
{chr(10).join(f'- {n}' for n in news)}

请输出以下 JSON 格式（仅输出 JSON，不要其他内容）：
{{
  "win_a_pct": 数字(0-100),
  "draw_pct": 数字(0-100),
  "win_b_pct": 数字(0-100),
  "prediction": "预测获胜方名称或平局",
  "confidence": 数字(50-95),
  "analysis": "200字以内中文深度分析",
  "key_factors": ["因素1", "因素2", "因素3"]
}}
确保 win_a_pct + draw_pct + win_b_pct = 100"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{CURRENT_CONFIG.gemini_model}:generateContent?key={CURRENT_CONFIG.gemini_api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()

    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    raw = raw.strip().lstrip("```json").rstrip("```").strip()
    return json.loads(raw)

# ─── OpenAI AI 预测 ───────────────────────────────────────
async def predict_with_openai(team_a: str, team_b: str, history: dict, news: list) -> dict:
    if not CURRENT_CONFIG.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API Key 未配置")

    prompt = f"""你是世界顶级足球数据分析师。分析以下比赛并给出预测。

比赛：{team_a} vs {team_b}
历史数据：{json.dumps(history, ensure_ascii=False)}
新闻：{'; '.join(news)}

仅输出 JSON：
{{"win_a_pct":数字,"draw_pct":数字,"win_b_pct":数字,"prediction":"名称","confidence":数字,"analysis":"分析","key_factors":["因素1","因素2","因素3"]}}"""

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{CURRENT_CONFIG.openai_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {CURRENT_CONFIG.openai_api_key}"},
            json={"model": CURRENT_CONFIG.openai_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
        )
        data = resp.json()
    raw = data["choices"][0]["message"]["content"].strip().lstrip("```json").rstrip("```").strip()
    return json.loads(raw)

# ─── 路由 ─────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.get("/api/historical/{team_a}/{team_b}")
async def get_history(team_a: str, team_b: str):
    data = get_historical(team_a, team_b)
    return {"team_a": team_a, "team_b": team_b, "data": data}

@app.post("/api/predict", response_model=PredictionResponse)
async def predict(req: PredictionRequest):
    # 缓存 key 需要包含影响结果的关键维度，避免不同条件误命中同一缓存
    provider = (CURRENT_CONFIG.ai_provider or AI_PROVIDER).strip().lower()
    cache_payload = {
        "team_a": req.team_a,
        "team_b": req.team_b,
        "match_date": req.match_date,
        "include_news": req.include_news,
        "provider": provider,
        "gemini_model": CURRENT_CONFIG.gemini_model,
        "openai_model": CURRENT_CONFIG.openai_model,
        "openai_base_url": CURRENT_CONFIG.openai_base_url,
    }
    cache_key = "pred:" + hashlib.md5(
        json.dumps(cache_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    # 缓存检查（1小时缓存）
    if r:
        cached = r.get(cache_key)
        if cached:
            return JSONResponse(content=json.loads(cached))

    history = get_historical(req.team_a, req.team_b)
    news = await fetch_news(req.team_a, req.team_b) if req.include_news else []

    try:
        if provider == "openai":
            ai_result = await predict_with_openai(req.team_a, req.team_b, history, news)
        else:
            ai_result = await predict_with_gemini(req.team_a, req.team_b, history, news)
    except Exception as e:
        # Fallback：基于历史数据的简单统计预测
        h = history
        total = h.get("h2h", 0) or 1
        wa = round((h.get("brazil_wins", h.get("ger_wins", h.get("eng_wins", 40))) / total) * 100, 1)
        wd = round((h.get("draws", 20) / total) * 100, 1)
        wb = round(100 - wa - wd, 1)
        ai_result = {
            "win_a_pct": wa, "draw_pct": wd, "win_b_pct": wb,
            "prediction": req.team_a if wa > wb else ("平局" if wd > wb else req.team_b),
            "confidence": 55,
            "analysis": f"基于{total}场历史交锋统计分析（AI 服务暂时不可用）",
            "key_factors": ["历史胜率", "近期状态", "主场优势"]
        }

    result = PredictionResponse(
        team_a=req.team_a, team_b=req.team_b,
        win_a_pct=ai_result["win_a_pct"],
        draw_pct=ai_result["draw_pct"],
        win_b_pct=ai_result["win_b_pct"],
        prediction=ai_result["prediction"],
        confidence=ai_result["confidence"],
        analysis=ai_result["analysis"],
        key_factors=ai_result.get("key_factors", []),
        historical_summary=history,
        news_insights=news,
        generated_at=datetime.utcnow().isoformat()
    )

    # 写入缓存
    if r:
        r.setex(cache_key, 3600, json.dumps(result.dict(), ensure_ascii=False))

    return result

@app.get("/api/teams")
async def get_teams():
    teams = [
        {"name": "Brazil", "cn": "巴西", "flag": "🇧🇷", "rank": 1},
        {"name": "Argentina", "cn": "阿根廷", "flag": "🇦🇷", "rank": 2},
        {"name": "France", "cn": "法国", "flag": "🇫🇷", "rank": 4},
        {"name": "England", "cn": "英格兰", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "rank": 5},
        {"name": "Spain", "cn": "西班牙", "flag": "🇪🇸", "rank": 7},
        {"name": "Germany", "cn": "德国", "flag": "🇩🇪", "rank": 3},
        {"name": "Portugal", "cn": "葡萄牙", "flag": "🇵🇹", "rank": 6},
        {"name": "Netherlands", "cn": "荷兰", "flag": "🇳🇱", "rank": 9},
        {"name": "Belgium", "cn": "比利时", "flag": "🇧🇪", "rank": 10},
        {"name": "Morocco", "cn": "摩洛哥", "flag": "🇲🇦", "rank": 11},
        {"name": "Japan", "cn": "日本", "flag": "🇯🇵", "rank": 12},
        {"name": "Croatia", "cn": "克罗地亚", "flag": "🇭🇷", "rank": 8},
    ]
    return {"teams": teams, "total": len(teams)}


def require_admin(password: str = Header(..., alias="X-Admin-Token")):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True


@app.get("/api/admin/config", response_model=ModelConfig)
async def get_model_config(_: bool = Depends(require_admin)):
    return CURRENT_CONFIG


class UpdateConfigRequest(BaseModel):
    ai_provider: str
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    news_api_key: str | None = None


@app.post("/api/admin/config", response_model=ModelConfig)
async def update_model_config(body: UpdateConfigRequest, _: bool = Depends(require_admin)):
    global CURRENT_CONFIG
    data = CURRENT_CONFIG.dict()
    for field, value in body.dict(exclude_unset=True).items():
        if value is not None:
            data[field] = value
    CURRENT_CONFIG = ModelConfig(**data)
    save_config(CURRENT_CONFIG)
    return CURRENT_CONFIG


ADMIN_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>模型配置面板</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans SC",sans-serif; background:#0b1020; color:#f7f7ff; margin:0; padding:24px; }
    .card { max-width:720px; margin:0 auto; background:#151a30; border-radius:12px; padding:24px 28px; box-shadow:0 18px 45px rgba(0,0,0,.55); border:1px solid rgba(255,255,255,.06); }
    h1 { margin-top:0; font-size:22px; }
    label { display:block; font-size:13px; margin-top:14px; margin-bottom:4px; opacity:.82; }
    input, select { width:100%; padding:8px 10px; border-radius:6px; border:1px solid rgba(255,255,255,.14); background:#111524; color:#f7f7ff; font-size:13px; box-sizing:border-box; }
    input:focus, select:focus { outline:none; border-color:#4f8df7; box-shadow:0 0 0 1px rgba(79,141,247,.45); }
    .row { display:flex; gap:12px; }
    .row > div { flex:1; }
    button { margin-top:20px; padding:10px 18px; border-radius:999px; border:none; background:linear-gradient(135deg,#4f8df7,#27c4f5); color:#fff; font-weight:600; cursor:pointer; font-size:13px; }
    button:disabled { opacity:.5; cursor:not-allowed; }
    .tag { display:inline-block; font-size:11px; padding:2px 8px; border-radius:999px; background:rgba(79,141,247,.15); color:#9bbcff; margin-left:8px; vertical-align:middle; }
    .hint { font-size:12px; opacity:.65; margin-top:4px; }
    .status { margin-top:10px; font-size:12px; }
    .status.ok { color:#38c793; }
    .status.err { color:#ff6b81; }
  </style>
</head>
<body>
  <div class="card">
    <h1>模型配置面板 <span class="tag">后端管理</span></h1>
    <p style="font-size:13px;opacity:.7;margin-bottom:14px;">通过此界面可以切换 Gemini / OpenAI / 自定义兼容接口，并更新对应的 Key、Base URL 与模型名。</p>

    <label>管理口令（X-Admin-Token）</label>
    <input id="adminToken" type="password" placeholder="默认：admin123，生产环境请在环境变量 ADMIN_PASSWORD 中修改" />

    <label style="margin-top:18px;">AI 提供商</label>
    <select id="aiProvider">
      <option value="gemini">Gemini</option>
      <option value="openai">OpenAI / 兼容接口</option>
    </select>

    <div class="row">
      <div>
        <label>Gemini API Key</label>
        <input id="geminiApiKey" type="password" placeholder="可留空，使用环境变量 GEMINI_API_KEY" />
      </div>
      <div>
        <label>Gemini 模型名</label>
        <input id="geminiModel" type="text" placeholder="如：gemini-pro" />
      </div>
    </div>

    <div class="row">
      <div>
        <label>OpenAI / 兼容接口 API Key</label>
        <input id="openaiApiKey" type="password" placeholder="可留空，使用环境变量 OPENAI_API_KEY" />
      </div>
      <div>
        <label>OpenAI 模型名</label>
        <input id="openaiModel" type="text" placeholder="如：gpt-4o-mini 或自定义模型名" />
      </div>
    </div>

    <label>OpenAI Base URL</label>
    <input id="openaiBaseUrl" type="text" placeholder="如：https://api.openai.com/v1 或 http://20230620.xyz:3030/v1" />
    <div class="hint">自定义兼容接口时请务必包含 /v1 前缀。</div>

    <label>News API Key</label>
    <input id="newsApiKey" type="password" placeholder="用于实时新闻分析，可留空关闭新闻功能" />

    <button id="saveBtn" onclick="saveConfig()">保存配置</button>
    <div id="status" class="status"></div>
  </div>

  <script>
    async function loadConfig() {
      const token = document.getElementById('adminToken').value.trim();
      if (!token) return;
      const res = await fetch('/api/admin/config', {
        headers: { 'X-Admin-Token': token }
      });
      const statusEl = document.getElementById('status');
      if (!res.ok) {
        statusEl.textContent = '加载失败：请确认管理口令是否正确';
        statusEl.className = 'status err';
        return;
      }
      const data = await res.json();
      document.getElementById('aiProvider').value = data.ai_provider;
      document.getElementById('geminiApiKey').value = data.gemini_api_key || '';
      document.getElementById('geminiModel').value = data.gemini_model || '';
      document.getElementById('openaiApiKey').value = data.openai_api_key || '';
      document.getElementById('openaiBaseUrl').value = data.openai_base_url || '';
      document.getElementById('openaiModel').value = data.openai_model || '';
      document.getElementById('newsApiKey').value = data.news_api_key || '';
      statusEl.textContent = '配置已加载';
      statusEl.className = 'status ok';
    }

    async function saveConfig() {
      const token = document.getElementById('adminToken').value.trim();
      if (!token) {
        alert('请先填写管理口令（X-Admin-Token）');
        return;
      }
      const body = {
        ai_provider: document.getElementById('aiProvider').value,
        gemini_api_key: document.getElementById('geminiApiKey').value || null,
        gemini_model: document.getElementById('geminiModel').value || null,
        openai_api_key: document.getElementById('openaiApiKey').value || null,
        openai_base_url: document.getElementById('openaiBaseUrl').value || null,
        openai_model: document.getElementById('openaiModel').value || null,
        news_api_key: document.getElementById('newsApiKey').value || null
      };
      const btn = document.getElementById('saveBtn');
      const statusEl = document.getElementById('status');
      btn.disabled = true;
      statusEl.textContent = '保存中...';
      statusEl.className = 'status';
      try {
        const res = await fetch('/api/admin/config', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Admin-Token': token
          },
          body: JSON.stringify(body)
        });
        if (!res.ok) {
          const err = await res.json().catch(()=>({detail:'未知错误'}));
          statusEl.textContent = '保存失败：' + (err.detail || res.status);
          statusEl.className = 'status err';
        } else {
          statusEl.textContent = '保存成功，新的配置已生效';
          statusEl.className = 'status ok';
        }
      } catch (e) {
        statusEl.textContent = '保存失败：网络异常';
        statusEl.className = 'status err';
      } finally {
        btn.disabled = false;
      }
    }

    document.getElementById('adminToken').addEventListener('blur', loadConfig);
  </script>
</body>
</html>
"""


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return HTMLResponse(content=ADMIN_HTML)
