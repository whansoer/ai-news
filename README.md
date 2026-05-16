# AI 新闻收集器

自动从 RSS、免费 API、网页抓取三种渠道采集 AI 新闻，展现在 GitHub Pages 上。

## 快速开始

1. Fork 或新建仓库，开启 GitHub Pages（Settings → Pages → Source: `main` 分支根目录）

2. （可选）设置 NewsAPI Key：
   - 在 https://newsapi.org 注册免费账号获取 API Key
   - 在仓库 Settings → Secrets → Actions 添加 `NEWSAPI_KEY`

3. 推送代码后，GitHub Actions 会自动运行采集，无需手动操作

4. 访问 `https://<你的用户名>.github.io/<仓库名>/`

## 本地运行

```bash
pip install -r scripts/requirements.txt
python scripts/collect.py
# 然后用任意 HTTP 服务打开 index.html
python -m http.server 8080
```

## 数据源

| 渠道 | 来源 |
|------|------|
| RSS | Hugging Face, OpenAI, Anthropic, Google AI, ArXiv, MIT Tech Review, The Verge, VentureBeat, MarkTechPost, Synced |
| API | NewsAPI（可选，需 Key） |
| 爬虫 | GitHub Trending AI/ML 仓库（可选） |
